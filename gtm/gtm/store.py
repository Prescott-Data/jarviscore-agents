"""Where the desk's memory of each account lives between runs.

A file per account, written only after the run has reported. State recorded
before a human is told is a signal that can be lost forever if the process dies
in between.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from gtm.accounts import Account
from gtm.state import AccountState

STATE_DIR_ENV = "GTM_STATE_DIR"
# Beside everything else JarvisCore writes at runtime.
DEFAULT_STATE_DIR = ".jarviscore/gtm/accounts"


@dataclass(frozen=True)
class AccountStore:
    """Reads and writes account dossiers as JSON."""

    base: Path

    @classmethod
    def from_env(cls) -> AccountStore:
        return cls(Path(os.getenv(STATE_DIR_ENV, DEFAULT_STATE_DIR)).expanduser())

    def _path(self, account_id: str) -> Path:
        return self.base / f"{account_id}.json"

    def load(self, account: Account) -> AccountState:
        path = self._path(account.account_id)
        if not path.is_file():
            return AccountState(account.account_id, account.name)
        return AccountState.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, state: AccountState) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        path = self._path(state.account_id)
        # Write-then-rename: a crash mid-write must not leave a half dossier.
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(state.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(path)
