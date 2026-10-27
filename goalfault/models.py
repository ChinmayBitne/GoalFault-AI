from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
from .spec import default_spec

Kind = Literal[default_spec().kinds]
Source = Literal["demo_template", "muse", "manual"]

class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Kind
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

class ComposeRequest(BaseModel):
    text: str = Field(min_length=12, max_length=1500)
    mode: Literal["demo", "muse"] = "demo"

class DiscoverRequest(BaseModel):
    mode: Literal["demo", "muse"] = "demo"

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
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    title: str = Field(min_length=5, max_length=120)
    user_message: str = Field(min_length=5, max_length=1500)
    risk: Literal["high", "critical"]
    explanation: str = Field(min_length=5, max_length=500)
