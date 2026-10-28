from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator
from .spec import DEFAULT_DOMAIN, IDENT, registry

Source = Literal["demo_template", "muse", "manual"]

class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    # Rows saved before domains existed have no domain field and belong to support.
    domain: str = Field(default=DEFAULT_DOMAIN, pattern=IDENT, max_length=60)
    kind: str = Field(pattern=IDENT, max_length=60)
    title: str = Field(min_length=5, max_length=120)
    description: str = Field(min_length=5, max_length=500)
    user_message: str = Field(min_length=5, max_length=1500)
    risk: Literal["high", "critical"]
    source: Source
    status: Literal["proposed", "approved", "rejected"] = "proposed"
    expected_invariant: str
    reviewed_at: str | None = None
    objective: str | None = Field(default=None, max_length=300)
    pressure_level: int = Field(default=0, ge=0, le=3)

    @model_validator(mode="after")
    def kind_belongs_to_domain(self):
        spec = registry().get(self.domain)
        if spec is None:
            raise ValueError(f"unknown domain {self.domain!r}")
        if self.kind not in spec.kinds:
            raise ValueError(f"{self.kind!r} is not a scenario kind of {self.domain}")
        return self

class ComposeRequest(BaseModel):
    text: str = Field(min_length=12, max_length=1500)
    mode: Literal["demo", "muse"] = "demo"
    domain: str = Field(default=DEFAULT_DOMAIN, pattern=IDENT, max_length=60)

class DiscoverRequest(BaseModel):
    mode: Literal["demo", "muse"] = "demo"
    domain: str = Field(default=DEFAULT_DOMAIN, pattern=IDENT, max_length=60)

class ReviewRequest(BaseModel):
    approved: bool
    title: str | None = Field(default=None, min_length=5, max_length=120)
    user_message: str | None = Field(default=None, min_length=5, max_length=1500)
    # Empty string clears the objective; omitted keeps the current value.
    objective: str | None = Field(default=None, max_length=300)
    pressure_level: int | None = Field(default=None, ge=0, le=3)

class RunRequest(BaseModel):
    mode: Literal["fixture", "muse"] = "fixture"
    guardrails: bool = False

class ReplayRequest(BaseModel):
    guardrails: bool = True

class ProposedScenario(BaseModel):
    """What a proposal returns. The kind is checked against the target domain by whoever asked for it."""
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern=IDENT, max_length=60)
    title: str = Field(min_length=5, max_length=120)
    user_message: str = Field(min_length=5, max_length=1500)
    risk: Literal["high", "critical"]
    explanation: str = Field(min_length=5, max_length=500)
