"""Loopback/same-origin boundaries, and last-mile structured-output redaction."""

import ipaddress
import os
import re
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|CONNECTION_STRING|DSN", re.I)
INLINE_SECRET = re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")


class Redactor:
    def __init__(self) -> None:
        self.values = sorted(
            {v for k, v in os.environ.items() if SECRET_NAME.search(k) and v},
            key=len,
            reverse=True,
        )

    def text(self, value: str) -> str:
        for secret in self.values:
            value = value.replace(secret, "[redacted]")
        return INLINE_SECRET.sub("[redacted]", value)


def authority(value: str, scheme: str) -> tuple[str, int] | None:
    try:
        parsed = urlsplit(f"{scheme}://{value}")
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return None
        if parsed.hostname not in LOCAL_HOSTS:
            return None
        port = parsed.port or (443 if scheme == "https" else 80)
        return parsed.hostname, port
    except ValueError:
        return None


class LocalOnlyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {}
        for key, value in scope["headers"]:
            headers.setdefault(key, []).append(value.decode("latin-1"))
        hosts = headers.get(b"host", [])
        scheme = scope["scheme"]
        host = authority(hosts[0], scheme) if len(hosts) == 1 else None
        client = scope.get("client")
        try:
            local_client = bool(client) and ipaddress.ip_address(client[0]).is_loopback
        except ValueError:
            local_client = False
        if not host or not local_client:
            return await JSONResponse({"detail": "Loopback access only."}, 403)(
                scope, receive, send
            )
        origins = headers.get(b"origin", [])
        if origins:
            try:
                origin = urlsplit(origins[0])
                same = (
                    len(origins) == 1
                    and origin.scheme == scheme
                    and not origin.path and not origin.query and not origin.fragment
                    and authority(origin.netloc, scheme) == host
                )
            except ValueError:
                same = False
            if not same:
                return await JSONResponse({"detail": "Cross-origin access denied."}, 403)(
                    scope, receive, send
                )
        if "cross-site" in headers.get(b"sec-fetch-site", []):
            # A cross-site fetch could drive the API from a hostile page. A
            # top-level GET navigation cannot: it reads nothing back and reaches
            # only a page. That is how the person returns from a provider's
            # consent screen, so it is allowed, as the Fetch Metadata resource
            # isolation policy allows it.
            navigation = (
                scope["method"] == "GET"
                and "navigate" in headers.get(b"sec-fetch-mode", [])
                and "document" in headers.get(b"sec-fetch-dest", [])
            )
            if not navigation:
                return await JSONResponse({"detail": "Cross-site access denied."}, 403)(
                    scope, receive, send
                )
        # No browser-supplied uploads or arbitrarily large JSON bodies.
        if scope["method"] == "POST":
            chunks, size = [], 0
            while True:
                part = await receive()
                if part["type"] == "http.disconnect":
                    return
                size += len(part.get("body", b""))
                if size > 32768:
                    return await JSONResponse({"detail": "Request too large."}, 413)(
                        scope, receive, send
                    )
                chunks.append(part)
                if not part.get("more_body", False):
                    break

            async def buffered_receive():
                return chunks.pop(0) if chunks else await receive()

            return await self.app(scope, buffered_receive, send)
        return await self.app(scope, receive, send)
