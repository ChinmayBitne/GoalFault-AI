from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

Kind = Literal["refund_authorization", "cross_account_access", "premature_closure"]
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

class ComposeRequest(BaseModel):
    text: str = Field(min_length=12, max_length=1500)
    mode: Literal["demo", "muse"] = "demo"

class DiscoverRequest(BaseModel):
    mode: Literal["demo", "muse"] = "demo"

class ReviewRequest(BaseModel):
    approved: bool
    title: str | None = Field(default=None, min_length=5, max_length=120)
    user_message: str | None = Field(default=None, min_length=5, max_length=1500)

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
