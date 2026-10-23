"""Trusted local configuration; never loaded from browser input."""

import hashlib
import importlib
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .adapters.process import ProcessAdapter
from .models import AgentMetadata, Operation, PublicRunError
from .registry import AdapterRegistry
from .store import desk_home

AGENT_COLORS = ("#397b72", "#bd6847", "#4975bd", "#b58b32", "#ab5876", "#438a9e")


def public_agent_id(factory, role, occurrence):
    return "agent-" + hashlib.sha256(f"{factory}:{role}:{occurrence}".encode()).hexdigest()[:16]


class Appearance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,63}$")
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    shape: Literal["circle", "rounded", "diamond", "hexagon"] = "circle"


class DeskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "JarvisCore Agents"
    factory: str
    mesh_handler: str | None = None
    mesh_reconcile_handler: str | None = None
    #: A room for people and agents (``module:async_function(mesh) -> Room``).
    room_factory: str | None = None
    blueprint: str = "custom"
    mesh_id: str = Field(default="mesh", pattern=r"^[a-z][a-z0-9-]{0,63}$")
    mesh_name: str = Field(default="Mesh", min_length=1, max_length=64)
    agents: dict[str, Appearance] = Field(default_factory=dict)
    working_dir: Path | None = None
    trace_dir: Path | None = None
    metrics_url: str | None = None
    required_framework_commit: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{40}$"
    )
    required_framework_version: str | None = None

    @field_validator("required_framework_version")
    @classmethod
    def framework_version_range(cls, value):
        if value is not None:
            from packaging.specifiers import InvalidSpecifier, SpecifierSet

            try:
                SpecifierSet(value)
            except InvalidSpecifier as error:
                raise ValueError(f"invalid version range {value!r}") from error
        return value

    @field_validator("metrics_url")
    @classmethod
    def metrics_address(cls, value):
        if value is not None:
            parts = urlsplit(value)
            unsafe = parts.username or parts.password or parts.query or parts.fragment
            if parts.scheme not in {"http", "https"} or not parts.hostname or unsafe:
                raise ValueError("Metrics endpoint must be an HTTP(S) URL without embedded secrets.")
        return value

    @field_validator("factory", "mesh_handler", "mesh_reconcile_handler")
    @classmethod
    def import_reference(cls, value):
        if value is not None:
            module, separator, symbol = value.partition(":")
            if not separator or not all(part.isidentifier() for part in module.split(".")) or not symbol.isidentifier():
                raise ValueError("Use an installed module:function reference.")
        return value


def resolve(reference):
    module, symbol = reference.split(":")
    result = getattr(importlib.import_module(module), symbol)
    if not callable(result):
        raise ValueError("Configured entry must be callable.")
    return result


def load_config(path):
    path = Path(path).expanduser().resolve()
    config = DeskConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    key = hashlib.sha256(str(path).encode()).hexdigest()[:12]
    config.working_dir = (
        (path.parent / config.working_dir).resolve() if config.working_dir is not None
        else desk_home() / "projects" / key
    )
    if config.trace_dir is not None:
        config.trace_dir = (path.parent / config.trace_dir).resolve()
    else:
        config.trace_dir = config.working_dir / "traces"
    return config


class ConfiguredAdapter(ProcessAdapter):
    def __init__(self, metadata, path, member, home=None):
        super().__init__(home)
        self.metadata, self.path, self.member = metadata, str(path), member

    async def execute(self, operation, message, emit, run_context=None):
        if operation != "task" or not message or not message.strip():
            raise PublicRunError("Enter a task before submitting.")
        context = dict(run_context or {})
        if self.member == "mesh" and context.get("run_id"):
            workflow_id = self.workflow_id_for_run(context["run_id"])
            thread = workflow_id.split(":", 1)[0].removeprefix("desk-")
            context.update({
                "workflow_id": f"desk-{thread}",
                "step_id": context["run_id"],
                "mesh_workflow_id": workflow_id,
            })
        await self.execute_worker(
            [self.path, self.member], emit,
            initial={"mode": "execute", "message": message, "context": context},
        )

    async def reconcile(self, operation, message, emit, run_context=None):
        config = load_config(self.path)
        if (
            self.member != "mesh"
            or config.mesh_reconcile_handler is None
            or operation != "task"
            or not message
        ):
            raise PublicRunError("This configured agent cannot reconcile a goal.")
        context = dict(run_context or {})
        if not context.get("run_id"):
            raise PublicRunError("The Desk run identity is unavailable.")
        workflow_id = self.workflow_id_for_run(context["run_id"])
        thread = workflow_id.split(":", 1)[0].removeprefix("desk-")
        context.update({
            "workflow_id": f"desk-{thread}",
            "step_id": context["run_id"],
            "mesh_workflow_id": workflow_id,
        })
        await self.execute_worker(
            [self.path, self.member], emit,
            initial={"mode": "reconcile", "message": message, "context": context},
        )

    def workflow_id_for_run(self, run_id: str) -> str:
        config = load_config(self.path)
        thread = re.sub(
            r"[^a-z0-9]+", "-", f"{config.blueprint}-{self.member}".lower()
        ).strip("-")
        return f"desk-{thread}:{run_id}"

    def working_directory(self):
        return load_config(self.path).working_dir


def configured_registry(path, home=None):
    path = Path(path).expanduser().resolve()
    config = load_config(path)
    if config.required_framework_commit:
        from .framework import require_framework_commit

        require_framework_commit(config.required_framework_commit)
    if config.required_framework_version:
        from .framework import require_framework_version

        require_framework_version(config.required_framework_version)
    mesh = resolve(config.factory)()
    members = list(mesh.agents)
    if not members:
        raise ValueError("Mesh factory returned no agents.")
    task = Operation(id="task", label="Send task", description="Execute through JarvisCore", allows_message=True)
    registry = AdapterRegistry()
    ids = []
    occurrences = {}
    for index, agent in enumerate(members):
        occurrence = occurrences.get(agent.role, 0)
        occurrences[agent.role] = occurrence + 1
        appearance = config.agents.get(agent.role, Appearance())
        identity = appearance.id or public_agent_id(config.factory, agent.role, occurrence)
        metadata = AgentMetadata(
            id=identity, name=appearance.name or agent.role.replace("_", " ").title(),
            description=getattr(agent, "description", "") or agent.role, blueprint=config.blueprint,
            capabilities=tuple(agent.capabilities), operations=(task,),
            color=appearance.color or AGENT_COLORS[index % len(AGENT_COLORS)], shape=appearance.shape,
        )
        registry.register(ConfiguredAdapter(metadata, path, f"{agent.role}:{occurrence}", home))
        ids.append(identity)
    unknown = set(config.agents) - {member.role for member in members}
    if unknown:
        raise ValueError(f"Appearance configured for unknown roles: {sorted(unknown)}")
    registry.register(ConfiguredAdapter(AgentMetadata(
        id=config.mesh_id, name=config.mesh_name, description=config.name, blueprint=config.blueprint,
        kind="mesh", members=tuple(ids), operations=(task,) if config.mesh_handler else (),
        supports_reconciliation=config.mesh_reconcile_handler is not None,
        color="#1758f5", shape="rounded",
    ), path, "mesh", home))
    registry.metadata()
    return config, registry
