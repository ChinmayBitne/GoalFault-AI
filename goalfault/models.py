from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from .compiler import MAX_EXAMPLES, DraftExample
from .rules import MAX_RULE_LENGTH
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

class SweepRequest(BaseModel):
    scenario_id: str = Field(max_length=40)
    levels: list[int] = Field(default=[0, 1, 2, 3], min_length=1, max_length=4)
    runs_per_level: int = Field(default=3, ge=1, le=10)
    confirm: bool = False

    @field_validator("levels")
    @classmethod
    def known_levels(cls, levels: list[int]) -> list[int]:
        if any(not 0 <= level <= 3 for level in levels):
            raise ValueError("pressure levels run from 0 to 3")
        return sorted(set(levels))

class PolicyEdit(BaseModel):
    """Fields a person can change on a compiled policy; anything left out keeps its current value."""
    model_config = ConfigDict(extra="forbid")
    text: str | None = Field(default=None, min_length=5, max_length=500)
    rule: str | None = Field(default=None, min_length=5, max_length=MAX_RULE_LENGTH)
    invariant: str | None = Field(default=None, pattern=IDENT, max_length=60)
    should_pass: list[DraftExample] | None = Field(default=None, max_length=MAX_EXAMPLES)
    should_fail: list[DraftExample] | None = Field(default=None, max_length=MAX_EXAMPLES)

class CompileRequest(PolicyEdit):
    text: str = Field(min_length=5, max_length=500)
    # manual: the person writes the rule and examples and gets the same checks, with no model call.
    mode: Literal["muse", "manual"] = "manual"

class PolicyReviewRequest(PolicyEdit):
    approved: bool

class DomainDraftRequest(BaseModel):
    """A business description. mode muse asks the model for a spec. manual supplies the YAML."""
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=12, max_length=1500)
    yaml: str | None = Field(default=None, min_length=20, max_length=80000)
    mode: Literal["manual", "muse"] = "manual"

class DomainReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool

class RepairRequest(BaseModel):
    """A rule meant to block one stored failing trace. mode muse asks the model to write the rule."""
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=5, max_length=500)
    rule: str | None = Field(default=None, min_length=5, max_length=MAX_RULE_LENGTH)
    invariant: str | None = Field(default=None, pattern=IDENT, max_length=60)
    mode: Literal["manual", "muse"] = "manual"

class ProposedScenario(BaseModel):
    """What a proposal returns. The kind is checked against the target domain by whoever asked for it."""
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern=IDENT, max_length=60)
    title: str = Field(min_length=5, max_length=120)
    user_message: str = Field(min_length=5, max_length=1500)
    risk: Literal["high", "critical"]
    explanation: str = Field(min_length=5, max_length=500)

class SandboxCallRequest(BaseModel):
    """An external agent tool call executed against an isolated scenario sandbox."""
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(pattern=IDENT, max_length=60)
    arguments: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = Field(default=None, max_length=60)
    enforce: bool = False
