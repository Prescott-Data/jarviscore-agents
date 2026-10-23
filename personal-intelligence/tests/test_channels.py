import sqlite3

from personal_intelligence.channels.telegram import TelegramOffsetStore, parse_private_text
from personal_intelligence.team import workflow_identity


def test_private_telegram_message_maps_to_stable_campaign_and_attempt():
    message = parse_private_text(
        {
            "update_id": 17,
            "message": {
                "message_id": 9,
                "message_thread_id": 3,
                "text": "Find my next role.",
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 7},
            },
        }
    )

    assert message is not None
    assert message.owner_id == "telegram:7"
    assert message.campaign_id == "telegram-chat:42:topic:3"
    context = {
        "owner_id": message.owner_id,
        "campaign_id": message.campaign_id,
        "source_event_id": message.source_event_id,
    }
    assert workflow_identity(context) == workflow_identity(context)
    next_attempt = workflow_identity(
        {**context, "source_event_id": "telegram:42:10"}
    )
    assert next_attempt != workflow_identity(context)


def test_telegram_channel_ignores_group_and_non_text_updates():
    assert parse_private_text({"update_id": 1, "message": {"chat": {"type": "group"}}}) is None
    assert parse_private_text({"update_id": 2, "callback_query": {}}) is None


def test_offset_store_persists_acknowledged_updates(tmp_path):
    path = tmp_path / "channels.db"
    store = TelegramOffsetStore(str(path))
    store.acknowledge(41)
    store.close()

    reopened = TelegramOffsetStore(str(path))
    assert reopened.next_offset() == 42
    reopened.close()
    sqlite3.connect(path).close()
