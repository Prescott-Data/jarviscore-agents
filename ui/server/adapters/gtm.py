"""Optional GTM fixture adapter used by the GTM package's own tests."""

from ..models import AgentMetadata, Emit, Operation, PublicRunError
from .process import ProcessAdapter


class GTMAdapter(ProcessAdapter):
    worker_module = "server.worker"
    metadata = AgentMetadata(
        id="gtm-account-expert", name="GTM Account Expert", blueprint="gtm",
        description="Account evidence and actual agent assessments, with durable local history.",
        operations=(
            Operation(
                id="sample", label="Fixture-data preview",
                description="Deterministic Globex fixture replay through real GTM source/state. "
                "No network, no LLM, and no significance judgements.",
            ),
            Operation(
                id="watch", label="Watch Monzo live",
                description="One live Monzo Greenhouse collection. First run records a baseline "
                "without judgement; subsequent changes use the real Mesh/LLM if configured.",
            ),
        ),
    )

    def working_directory(self):
        return self.home / "gtm" / "runtime"

    async def execute(
        self, operation: str, message: str | None, emit: Emit, run_context=None
    ) -> None:
        if operation not in {"sample", "watch"} or message is not None:
            raise PublicRunError("Unsupported GTM operation or message.")
        await self.execute_worker([operation], emit)


class GTMMeshAdapter(GTMAdapter):
    metadata = AgentMetadata(
        id="gtm-mesh", name="Mesh", blueprint="gtm", kind="mesh",
        description="GTM mesh. Only Account Expert is implemented; available operations run that member.",
        members=("gtm-account-expert",), operations=GTMAdapter.metadata.operations,
        color="#1758f5", shape="rounded",
    )
