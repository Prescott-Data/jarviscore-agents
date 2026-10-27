"""Register Claims Hub with your Nexus broker, once, as an administrator would.

    python -m claims.setup_nexus      # NEXUS_BROKER_URL, NEXUS_BROKER_API_KEY, CLAIMS_HUB_URL

Claims Hub is an OAuth 2 provider: each person signs in to their own account and
consents, and Nexus holds their token. ``api_base_url`` is Claims Hub's own host,
the only one its credentials are ever sent to.
"""

from __future__ import annotations

import os
import sys

import httpx
from jarviscore.nexus.providers import broker_name

from claims.team import PROVIDER, claims_hub_url


def register(broker_url: str, api_key: str, base_url: str) -> dict:
    profile = {
        "name": broker_name(PROVIDER),   # Nexus's name for it: claims-hub
        "auth_type": "oauth2",
        "auth_url": f"{base_url}/oauth/authorize",
        "token_url": f"{base_url}/oauth/token",
        "client_id": os.environ.get("CLAIMS_HUB_CLIENT_ID", "jarviscore-agents"),
        "client_secret": os.environ.get("CLAIMS_HUB_CLIENT_SECRET", "claims-hub-local-secret"),
        "scopes": ["claims:read", "claims:write"],
        "api_base_url": base_url,
        "user_info_endpoint": "/api/me",
    }
    with httpx.Client(base_url=broker_url, headers={"X-API-Key": api_key}, timeout=10) as broker:
        listed = broker.get("/providers")
        listed.raise_for_status()
        rows = listed.json() or []
        rows = rows if isinstance(rows, list) else rows.get("providers") or []
        existing = next((p for p in rows if p.get("name") == profile["name"]), None)
        if existing is not None:
            return existing
        created = broker.post("/providers", json={"profile": profile})
        created.raise_for_status()
        return created.json()


def main() -> None:
    register(os.environ.get("NEXUS_BROKER_URL", "http://127.0.0.1:18080"),
             os.environ.get("NEXUS_BROKER_API_KEY", "broker-key"), claims_hub_url())
    print(f"Claims Hub is registered with Nexus as {broker_name(PROVIDER)}", file=sys.stderr)


if __name__ == "__main__":
    main()
