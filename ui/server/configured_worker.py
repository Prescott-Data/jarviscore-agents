"""Isolated worker for a trusted configured JarvisCore mesh."""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from .models import clean_event
from .security import Redactor


def failure_frame(error: BaseException, redact) -> str:
    data = clean_event(
        "error",
        {
            "message": (
                "The isolated worker failed before completion: "
                f"{type(error).__name__}: {error}"
            )
        },
        redact,
    )
    return json.dumps({"type": "error", "data": data}, ensure_ascii=False)


async def _run(emit):
    from .framework import framework_info, require_framework_source
    from .native import run_configured

    request = json.loads(await asyncio.to_thread(sys.stdin.readline))
    expected = os.environ.get("JARVISCORE_FRAMEWORK_SOURCE")
    info = await asyncio.to_thread(
        require_framework_source, Path(expected),
    ) if expected else await asyncio.to_thread(framework_info)
    revision = info["framework_revision"]
    details = (
        f"; {info['framework_branch']} at {revision[:12]}"
        f"{' with local changes' if info['framework_dirty'] else ''}"
    ) if revision else "; installed distribution"
    await emit("status", {"message": f"Worker runtime: JarvisCore {info['framework_version']}{details}."})
    await run_configured(
        sys.argv[1], sys.argv[2], request["message"], emit,
        execution_context=request.get("context") or {},
        execution_mode=request.get("mode") or "execute",
    )


def main():
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1, encoding="utf-8")
    log = os.fdopen(os.dup(sys.stderr.fileno()), "w", buffering=1, encoding="utf-8")
    with open(os.devnull, "w") as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
        sys.stdout = sys.stderr = sink
        redactor = Redactor()

        class _RedactedLog(logging.Handler):
            def emit(self, record):
                log.write(redactor.text(self.format(record)) + "\n")

        # Warnings and errors go to the run's private log, with secrets removed; the protocol stays clean.
        handler = _RedactedLog(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
        # The model SDK retries timeouts and rate limits silently at INFO; those waits belong in the log.
        logging.getLogger("openai._base_client").setLevel(logging.INFO)
        emit_lock = asyncio.Lock()

        async def emit(kind, data):
            async with emit_lock:
                clean = clean_event(kind, data, redactor.text)
                protocol.write(json.dumps({"type": kind, "data": clean}, ensure_ascii=False) + "\n")
                protocol.flush()
                if await asyncio.to_thread(sys.stdin.readline) != "ack\n":
                    raise RuntimeError("Desk disconnected before persistence acknowledgement")

        try:
            asyncio.run(_run(emit))
        except BaseException as exc:  # noqa: BLE001
            protocol.write(failure_frame(exc, redactor.text) + "\n")
            protocol.flush()
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
