"""Explicit adapter registry; optional installed, trusted-local entry points."""

from importlib.metadata import entry_points

from .models import Adapter, AgentMetadata


class AdapterRegistry:
    def __init__(self, adapters=()):
        self.adapters: dict[str, Adapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: Adapter) -> None:
        metadata = AgentMetadata.model_validate(adapter.metadata)
        operations = [operation.id for operation in metadata.operations]
        if len(operations) != len(set(operations)) or (not operations and metadata.kind != "mesh"):
            raise ValueError("Agent operations must be nonempty and operations must be unique.")
        if metadata.id in self.adapters:
            raise ValueError("Duplicate adapter id.")
        if not callable(getattr(adapter, "execute", None)):
            raise ValueError("Adapter must implement async execute.")
        self.adapters[metadata.id] = adapter

    def load_installed(self) -> None:
        # Entry points are no-argument factories. CLI opt-in only; no browser imports.
        for entry in sorted(entry_points(group="jarviscore_agents.ui"), key=lambda ep: ep.name):
            self.register(entry.load()())

    def metadata(self) -> list[dict]:
        for adapter in self.adapters.values():
            for member in adapter.metadata.members:
                if member not in self.adapters or self.adapters[member].metadata.kind != "agent":
                    raise ValueError(f"Mesh member {member!r} is not a registered agent.")
        return [adapter.metadata.model_dump(mode="json") for adapter in self.adapters.values()]
