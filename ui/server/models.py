"""Public HTTP contracts and the deliberately small adapter event surface."""

import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    label: str
    description: str
    allows_message: bool = False


class AgentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    name: str
    description: str
    blueprint: str
    operations: tuple[Operation, ...]
    kind: Literal["agent", "mesh"] = "agent"
    members: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    supports_reconciliation: bool = False
    color: str = Field(default="#397b72", pattern=r"^#[0-9a-fA-F]{6}$")
    shape: Literal["circle", "rounded", "diamond", "hexagon"] = "circle"


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    agent_id: str = Field(min_length=1, max_length=64)
    operation: str = Field(min_length=1, max_length=64)
    message: str | None = Field(default=None, max_length=8000)
    source_context: dict[str, Any] = Field(default_factory=dict)


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    connection_id: str = Field(min_length=1, max_length=128)


class PeerContribution(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sender_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    text: str = Field(min_length=1, max_length=200000)


class PeerMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    recipient_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    messages: list[PeerContribution] = Field(min_length=1, max_length=32)


class ArtifactPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["text", "image", "pdf"]
    text: str | None = Field(default=None, max_length=20000)
    url: str | None = Field(default=None, max_length=4000, pattern=r"^https://")

    def model_post_init(self, __context) -> None:
        if self.kind == "text" and (not self.text or self.url):
            raise ValueError("Text previews require text.")
        if self.kind in {"image", "pdf"} and (not self.url or self.text):
            raise ValueError("Media previews require an HTTPS URL.")
        if self.url:
            parsed = urlsplit(self.url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Preview URLs require an HTTPS origin without credentials.")


class ArtifactResource(BaseModel):
    """A provider-neutral, user-visible work product produced by an agent."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1"] = "1"
    id: str = Field(min_length=1, max_length=256)
    artifact_type: Literal[
        "document", "presentation", "spreadsheet", "pdf", "email",
        "image", "audio", "video", "archive", "file",
    ]
    title: str = Field(min_length=1, max_length=240)
    url: str | None = Field(default=None, max_length=4000, pattern=r"^https://")
    mime_type: str | None = Field(default=None, max_length=160)
    provider: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, str] = Field(default_factory=dict)
    preview: ArtifactPreview | None = None

    def model_post_init(self, __context) -> None:
        if len(self.metadata) > 12 or any(
            not key or len(key) > 80 or len(value) > 1000
            for key, value in self.metadata.items()
        ):
            raise ValueError("Artifact metadata exceeds the public display limits.")
        if self.url:
            parsed = urlsplit(self.url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Artifact URLs require an HTTPS origin without credentials.")


EventType = Literal[
    "status", "result", "structured_output", "artifact", "error", "peer_message",
    "consent_required", "credential_input_required", "approval_required", "waiting",
    "activity",
]
Emit = Callable[[EventType, dict[str, Any]], Awaitable[None]]
TERMINAL = frozenset({"completed", "failed", "cancelled", "interrupted"})


class Adapter(Protocol):
    """Trusted implementation; execute must cooperate with task cancellation.

    Emit only public status/result/error data, never raw logs or model traces.
    Return to complete; raise to fail. The runtime owns terminal events.
    """

    metadata: AgentMetadata

    async def execute(
        self, operation: str, message: str | None, emit: Emit, run_context=None
    ) -> None: ...


class PublicRunError(RuntimeError):
    """Reserved for fixed, intentionally public errors from trusted adapters."""


class ConsentRequest(BaseModel):
    """An agent needs an account connected before it can act."""

    model_config = ConfigDict(extra="forbid", strict=True)
    provider: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=80)
    auth_url: str = Field(min_length=1, max_length=4000, pattern=r"^https://")


class WaitingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: str = Field(min_length=1, max_length=64)
    connection_id: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=256)
    step_id: str = Field(min_length=1, max_length=256)


class CredentialInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=80)
    connection_id: str = Field(min_length=1, max_length=128)
    state: str = Field(min_length=1, max_length=4000)
    schema: dict[str, Any]


class ActivityEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["reasoning", "tool", "agent", "decision"]
    summary: str = Field(min_length=1, max_length=240)
    agent: str | None = Field(default=None, max_length=100)
    tool: str | None = Field(default=None, max_length=100)
    outcome: Literal["started", "succeeded", "failed"] | None = None


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: str = Field(min_length=64, max_length=64)
    action: str = Field(min_length=1, max_length=1000)
    consequence: str = Field(min_length=1, max_length=1000)


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: str = Field(min_length=64, max_length=64)
    approved: bool


class ResultEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(max_length=200000)
    obligation_status: Literal["satisfied", "blocked", "incomplete"] | None = None


class StructuredOutputEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1"] = "1"
    output_type: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    title: str = Field(min_length=1, max_length=240)
    data: dict[str, Any]

    def model_post_init(self, __context) -> None:
        if len(json.dumps(self.data, ensure_ascii=False, default=str)) > 500000:
            raise ValueError("Structured output exceeds the public display limit.")


def clean_event(kind, data, redact):
    if kind == "peer_message":
        peer = PeerMessage.model_validate(data)
        if sum(len(message.text) for message in peer.messages) > 200000:
            raise ValueError("Peer messages exceed the event size limit.")
        return {"recipient_id": peer.recipient_id, "messages": [
            {"sender_id": message.sender_id, "text": redact(message.text)}
            for message in peer.messages
        ]}
    if kind == "artifact":
        artifact = ArtifactResource.model_validate(data)
        public = artifact.model_dump(exclude_none=True)
        for key in ("title", "description"):
            if key in public:
                public[key] = redact(public[key])
        public["metadata"] = {
            redact(key): redact(value) for key, value in public.get("metadata", {}).items()
        }
        if public.get("preview", {}).get("text"):
            public["preview"]["text"] = redact(public["preview"]["text"])
        return public
    if kind == "structured_output":
        structured = StructuredOutputEvent.model_validate(data)
        public = structured.model_dump()
        public["title"] = redact(public["title"])
        serialized = json.dumps(public["data"], ensure_ascii=False, default=str)
        public["data"] = json.loads(redact(serialized))
        return public
    key = "text" if kind == "result" else "message"
    if kind == "consent_required":
        consent = ConsentRequest.model_validate(data)
        # The URL is the provider's own consent page and carries no secret of
        # ours, so it is passed through: redacting it would break the click.
        return {"provider": consent.provider, "label": consent.label, "auth_url": consent.auth_url}
    if kind == "credential_input_required":
        capture = CredentialInputRequest.model_validate(data)
        return capture.model_dump()
    if kind == "activity":
        return ActivityEvent.model_validate(data).model_dump(exclude_none=True)
    if kind == "approval_required":
        return ApprovalRequest.model_validate(data).model_dump()
    if kind == "waiting":
        waiting = WaitingRequest.model_validate(data)
        return waiting.model_dump()
    if kind == "result":
        result = ResultEvent.model_validate(data).model_dump(exclude_none=True)
        result["text"] = redact(result["text"])
        return result
    if kind not in {"status", "result", "error"} or not isinstance(data, dict):
        raise ValueError("Invalid adapter event")
    if set(data) != {key} or not isinstance(data[key], str) or len(data[key]) > 200000:
        raise ValueError("Invalid adapter data")
    return {key: redact(data[key])}


class RoomMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=8000)
    thread: str | None = Field(default=None, max_length=128)


class RoomPress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person: str = Field(min_length=1, max_length=64)
    action: Literal["accept", "show_change", "release", "discard", "confirm", "cancel",
                    "approve", "decline"]
    # An approval's target names its work and the action's fingerprint.
    target: str = Field(min_length=1, max_length=256)
    thread: str | None = Field(default=None, max_length=128)
