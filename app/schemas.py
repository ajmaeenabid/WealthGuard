"""All pydantic models. Agreed on Day 1; additions beyond CLAUDE.md are marked (ext)."""
from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

AssetClass = Literal["cash", "bond", "equity_fund", "balanced_fund", "gold", "structured_note"]
Bucket = Literal["Conservative", "Moderate", "Balanced", "Growth", "Aggressive"]
Experience = Literal["none", "basic", "advanced"]


class Product(BaseModel):
    id: str
    name: str
    asset_class: AssetClass
    risk_level: int = Field(ge=1, le=5)
    expected_return: float
    volatility: float
    annual_fee_pct: float
    min_invest_cny: float
    lockup_days: int
    complex: bool
    description: str


class ClientProfile(BaseModel):
    id: str
    name: str = "Client"
    age: int
    horizon_years: float
    goal: str
    monthly_income_cny: float
    liquidity_need_pct: float
    experience: Experience
    risk_tolerance_score: float = Field(ge=0, le=100)
    risk_capacity_score: float = Field(ge=0, le=100)
    bucket: Bucket
    investable_amount_cny: float = 100000
    goal_target_cny: Optional[float] = None


class AllocationLine(BaseModel):
    product_id: str
    weight: float
    rationale: str


class Allocation(BaseModel):
    id: str = ""
    client_id: str
    lines: list[AllocationLine]
    expected_return: float
    volatility: float
    created_at: str
    summary: str = ""
    client_text: str = ""


class ComplianceCheck(BaseModel):
    rule_id: str
    passed: bool
    detail: str


class ComplianceResult(BaseModel):
    allocation_id: str
    passed: bool
    checks: list[ComplianceCheck]
    required_disclosures: list[str]


class AuditEntry(BaseModel):
    id: int
    ts: str
    actor: Literal["client", "agent", "compliance", "system"]
    action: str
    tier: str
    payload_hash: str
    prev_hash: str
    entry_hash: str


class OrderTicket(BaseModel):
    id: str
    client_id: str
    allocation_id: str
    status: Literal["draft", "awaiting_approval", "approved", "rejected"]
    sandbox: bool = True
    kind: Literal["order", "report"] = "order"
    detail: str = ""


class SessionReq(BaseModel):
    persona_id: Optional[str] = None


class ChatReq(BaseModel):
    client_id: str
    message: str = Field(max_length=4000)


class TranslateReq(BaseModel):
    client_id: Optional[str] = None
    target: Literal["en", "zh"]
    texts: list[Annotated[str, Field(max_length=2000)]] = Field(max_length=40)


class CompareReq(BaseModel):
    product_ids: list[str]
    client_id: Optional[str] = None


class ProfileReq(BaseModel):
    client_id: str
    answers: dict[str, object]


class AllocationReq(BaseModel):
    client_id: str
    preferred_ids: list[str] = []


class StressReq(BaseModel):
    allocation_id: str
    scenario: str


class DocumentReq(BaseModel):
    client_id: str
    filename: str
    text: str = Field(max_length=50000)


class ApproveReq(BaseModel):
    client_id: str


class StrictArgs(BaseModel):

    model_config = ConfigDict(extra="forbid")


LedgerStatus = Literal["planned", "bought", "cancelled"]
LedgerCategory = Literal["food", "transport", "shopping", "entertainment", "health", "housing", "education", "other"]


class LedgerEntry(BaseModel):
    id: str
    client_id: str
    ts: str
    item: str = Field(min_length=1, max_length=80)
    category: LedgerCategory = "other"
    amount_cny: float = Field(gt=0, le=10_000_000)
    status: LedgerStatus = "bought"
    impulse: bool = False
    source: Literal["typed", "voice", "sample"] = "typed"
    updated: str = ""


class LedgerIn(BaseModel):
    client_id: str
    item: str = Field(min_length=1, max_length=80)
    category: LedgerCategory = "other"
    amount_cny: float = Field(gt=0, le=10_000_000)
    status: LedgerStatus = "bought"
    impulse: bool = False
    ts: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class LedgerPatch(BaseModel):
    client_id: str
    item: Optional[str] = Field(default=None, min_length=1, max_length=80)
    category: Optional[LedgerCategory] = None
    amount_cny: Optional[float] = Field(default=None, gt=0, le=10_000_000)
    status: Optional[LedgerStatus] = None
    impulse: Optional[bool] = None


class LedgerCommandReq(BaseModel):
    client_id: str
    text: str = Field(min_length=1, max_length=300)
    source: Literal["typed", "voice"] = "typed"


class LedgerSampleReq(BaseModel):
    client_id: str
    kind: Literal["balanced", "heavy"] = "balanced"


class ReplayStartReq(BaseModel):
    client_id: str
    episode: str = Field(max_length=40)
    portfolio: Literal["mine", "equity"] = "mine"


class ReplayStepReq(BaseModel):
    client_id: str
    choice: Optional[str] = Field(default=None, max_length=20)
