"""Telegram is a channel into the Personal Intelligence harness, not its runtime."""

from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

from personal_intelligence.team import build_mesh, submit_task


@dataclass(frozen=True)
class TelegramMessage:
    update_id: int
    message_id: int
    chat_id: int
    user_id: int
    text: str
    thread_id: int | None = None

    @property
    def owner_id(self) -> str:
        return f"telegram:{self.user_id}"

    @property
    def campaign_id(self) -> str:
        topic = self.thread_id if self.thread_id is not None else "main"
        return f"telegram-chat:{self.chat_id}:topic:{topic}"

    @property
    def source_event_id(self) -> str:
        return f"telegram:{self.chat_id}:{self.message_id}"


def parse_private_text(update: dict[str, Any]) -> TelegramMessage | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    sender = message.get("from")
    text = message.get("text")
    if (
        not isinstance(chat, dict)
        or chat.get("type") != "private"
        or not isinstance(sender, dict)
        or not isinstance(text, str)
        or not text.strip()
    ):
        return None
    return TelegramMessage(
        update_id=int(update["update_id"]),
        message_id=int(message["message_id"]),
        chat_id=int(chat["id"]),
        user_id=int(sender["id"]),
        text=text.strip(),
        thread_id=(
            int(message["message_thread_id"])
            if message.get("message_thread_id") is not None
            else None
        ),
    )


class TelegramOffsetStore:
    def __init__(self, path: str):
        database = Path(path).expanduser()
        database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS channel_state "
            "(key TEXT PRIMARY KEY, value INTEGER NOT NULL)"
        )
        self.connection.commit()

    def next_offset(self) -> int | None:
        row = self.connection.execute(
            "SELECT value FROM channel_state WHERE key = 'telegram_offset'"
        ).fetchone()
        return int(row[0]) if row else None

    def acknowledge(self, update_id: int) -> None:
        self.connection.execute(
            "INSERT INTO channel_state(key, value) VALUES('telegram_offset', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = MAX(value, excluded.value)",
            (update_id + 1,),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


class TelegramAPI:
    def __init__(self, token: str, session: aiohttp.ClientSession):
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.session = session

    async def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": 30,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        data = await self._request("getUpdates", payload, timeout=40)
        result = data.get("result")
        return result if isinstance(result, list) else []

    async def send_message(
        self, chat_id: int, text: str, thread_id: int | None = None
    ) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text[:4096]}
        if thread_id is not None:
            payload["message_thread_id"] = thread_id
        await self._request("sendMessage", payload)

    async def send_action(self, chat_id: int, thread_id: int | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "action": "typing"}
        if thread_id is not None:
            payload["message_thread_id"] = thread_id
        await self._request("sendChatAction", payload)

    async def _request(
        self, method: str, payload: dict[str, Any], timeout: float = 15
    ) -> dict[str, Any]:
        async with self.session.post(
            f"{self.base_url}/{method}", json=payload, timeout=timeout
        ) as response:
            data = await response.json()
            if response.status >= 400 or not data.get("ok"):
                raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
            return data


class PersonalIntelligenceTelegramBot:
    def __init__(self, api: TelegramAPI, store: TelegramOffsetStore):
        self.api = api
        self.store = store
        self.mesh = build_mesh()

    async def run(self) -> None:
        await self.mesh.start()
        try:
            while True:
                updates = await self.api.get_updates(self.store.next_offset())
                for update in updates:
                    await self.handle_update(update)
                    self.store.acknowledge(int(update["update_id"]))
        finally:
            await self.mesh.stop()
            self.store.close()

    async def handle_update(self, update: dict[str, Any]) -> None:
        message = parse_private_text(update)
        if message is None:
            return
        if message.text in {"/start", "/help"}:
            await self.api.send_message(
                message.chat_id,
                "Tell me the outcome you want, the constraints that matter, "
                "and when you need it.",
                message.thread_id,
            )
            return
        await self.api.send_action(message.chat_id, message.thread_id)
        result = await submit_task(
            self.mesh,
            message.text,
            context={
                "owner_id": message.owner_id,
                "campaign_id": message.campaign_id,
                "source_event_id": message.source_event_id,
                "source_context": {
                    "channel": "telegram",
                    "chat_id": str(message.chat_id),
                    "thread_id": str(message.thread_id or ""),
                },
            },
        )
        response = str(result.get("result_summary") or "").strip()
        if result["status"] == "yield":
            response = "I need your approval or access to an app. Open Agent Desk to continue."
        elif not response:
            response = "I could not complete this request. Open Agent Desk to see what happened."
        await self.api.send_message(message.chat_id, response, message.thread_id)


async def _run() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    state_path = os.environ.get(
        "PERSONAL_INTELLIGENCE_CHANNEL_STATE",
        ".jarviscore/personal-intelligence/telegram.db",
    )
    async with aiohttp.ClientSession() as session:
        bot = PersonalIntelligenceTelegramBot(
            TelegramAPI(token, session), TelegramOffsetStore(state_path)
        )
        await bot.run()


def main() -> None:
    asyncio.run(_run())
