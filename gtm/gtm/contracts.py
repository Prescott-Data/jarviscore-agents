"""What the desk's agents return. Each model is an agent's ``output_schema``.

JarvisCore types the agent's final ``done`` call from the schema, so the model
fills these fields natively instead of writing JSON for us to parse.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Judgement(BaseModel):
    """One change, judged."""

    id: str = Field(description="The change id, copied exactly as given.")
    significance: Literal["act", "note", "ignore"]
    because: str = Field(
        min_length=1, description="One sentence justifying the verdict against the mandate."
    )


class Assessment(BaseModel):
    """The Account Expert's verdict on every reportable change for one account."""

    judgements: list[Judgement] = Field(
        description="Exactly one judgement per change shown, and nothing else."
    )

    @property
    def actionable(self) -> list[Judgement]:
        return [j for j in self.judgements if j.significance == "act"]

    def require_exactly(self, change_ids: Iterable[str]) -> Assessment:
        """A judgement nobody made must not be quietly invented or dropped."""
        expected = set(change_ids)
        judged = [j.id for j in self.judgements]
        problems = []
        if unknown := sorted(set(judged) - expected):
            problems.append(f"judged unknown changes {unknown}")
        if missing := sorted(expected - set(judged)):
            problems.append(f"left {missing} unjudged")
        if len(judged) != len(set(judged)):
            problems.append("judged a change more than once")
        if problems:
            raise ValueError("; ".join(problems))
        return self


class Finding(BaseModel):
    claim: str = Field(min_length=1)
    source: str = Field(
        min_length=1, description="The URL, record id or tool result the claim rests on."
    )


class Action(BaseModel):
    action: str = Field(min_length=1)
    state: Literal["proposed", "drafted", "done"] = Field(
        description="proposed: recommended only. drafted/done: a provider returned a record."
    )
    system: str | None = None
    record_id: str | None = Field(
        default=None, description="The id the provider returned. Required unless proposed."
    )

    @model_validator(mode="after")
    def provider_proof(self) -> Action:
        if self.state != "proposed" and not self.record_id:
            raise ValueError("a drafted or done action needs the provider's record id")
        return self


class GTMBrief(BaseModel):
    """The GTM agent's answer: what it found, what it did, and what is still open."""

    decision: Literal["proceed", "hold", "reject"]
    summary: str = Field(min_length=1, description="What the person should know, in prose.")
    findings: list[Finding] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
