"""Isolated browser-test server. Never used by the live desk launcher."""

import os

from fastapi.responses import StreamingResponse

from server.adapters.gtm import GTMAdapter
from server.adapters.gtm_team import default_gtm_registry
from server.app import create_app
from server.models import AgentMetadata, Operation
from server.store import desk_home


class OfflineValidation(GTMAdapter):
    metadata = AgentMetadata(
        id="offline-check", name="Offline validation", blueprint="tests",
        description="Test-only deterministic worker", operations=(
            Operation(id="check", label="Offline validation", description="No network or model calls"),
        ),
    )

    async def execute(self, operation, message, emit):
        if operation != "check" or message is not None:
            raise ValueError("Invalid test operation")
        await super().execute("sample", None, emit)


os.environ["PYTHON_DOTENV_DISABLED"] = "1"
home = desk_home()
config, registry = default_gtm_registry(home)
registry.register(OfflineValidation(home))
app = create_app(home=home, config=config, registry=registry)


@app.middleware("http")
async def interrupt_test_stream(request, call_next):
    response = await call_next(request)
    if request.url.path != "/api/runs/stream" or request.headers.get("x-test-disconnect") != "1":
        return response

    async def first_frame():
        try:
            async for chunk in response.body_iterator:
                yield chunk
                break
        finally:
            await response.body_iterator.aclose()

    return StreamingResponse(first_frame(), headers=dict(response.headers))
