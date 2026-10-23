"""Which accounts the desk watches, and why.

``why`` is not documentation. It is the only thing that lets an agent answer
"why this account, now" — a change means something different at an account you
are watching because a renewal is due than at one you are watching because a
competitor is embedded there. It is prepended to every assessment, so it is the
highest-leverage line in the file.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Account:
    """One account on the desk."""

    account_id: str
    name: str
    domain: str
    why: str

    def __post_init__(self) -> None:
        for name in ("account_id", "name", "domain", "why"):
            if not getattr(self, name, "").strip():
                raise ValueError(
                    f"{name} is required — an account with no stated reason for "
                    "being watched cannot be assessed against anything"
                )
