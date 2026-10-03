from pydantic import BaseModel, ConfigDict, field_validator
from datetime import datetime
from typing import Optional, List
from .models import OutcomeEnum, FailureReasonEnum, SourceEnum, MergeDecisionEnum

# ── Address ───────────────────────────────────────────────────────────────────
class AddressBase(BaseModel):
    address_id: str
    raw_text: str
    area: str

class AddressCreate(AddressBase):
    @field_validator("address_id")
    @classmethod
    def validate_address_id(cls, v):
        if not v or not v.strip():
            raise ValueError("address_id must not be empty")
        if len(v) > 100:
            raise ValueError("address_id exceeds 100 characters")
        return v.strip()

    @field_validator("raw_text")
    @classmethod
    def validate_raw_text(cls, v):
        if not v or not v.strip():
            raise ValueError("raw_text must not be empty")
        return v.strip()

    @field_validator("area")
    @classmethod
    def validate_area(cls, v):
        allowed = {"apartment", "gated community", "industrial", "standalone house"}
        if v.lower() not in allowed:
            raise ValueError(f"area must be one of: {allowed}")
        return v.lower()

class AddressResponse(AddressBase):
    canonical_id: Optional[str] = None
    is_archived: bool = False
    model_config = ConfigDict(from_attributes=True)

# ── AccessNote ────────────────────────────────────────────────────────────────
class AccessNoteBase(BaseModel):
    instruction_text: str

class AccessNoteCreate(AccessNoteBase):
    address_id: str
    source: SourceEnum = SourceEnum.DRIVER_LOGGED

    @field_validator("instruction_text")
    @classmethod
    def validate_instruction_text(cls, v):
        if not v or not v.strip():
            raise ValueError("instruction_text must not be empty")
        if len(v.strip()) < 5:
            raise ValueError("instruction_text too short — must be at least 5 characters")
        return v.strip()

class AccessNoteResponse(AccessNoteBase):
    note_id: int
    address_id: str
    source: SourceEnum
    created_at: datetime
    last_confirmed_at: datetime
    confirmation_count: int
    contradiction_count: int
    
    model_config = ConfigDict(from_attributes=True)

# ── DeliveryAttempt ───────────────────────────────────────────────────────────
class DeliveryAttemptBase(BaseModel):
    address_id: str
    outcome: OutcomeEnum
    failure_reason: Optional[FailureReasonEnum] = FailureReasonEnum.NONE
    driver_id: str
    used_note_id: Optional[int] = None
    promised_slot: Optional[str] = "10:00-13:00 slot"
    is_within_sla: Optional[bool] = True

    @field_validator("driver_id")
    @classmethod
    def validate_driver_id(cls, v):
        if not v or not v.strip():
            raise ValueError("driver_id must not be empty")
        return v.strip()

class DeliveryAttemptCreate(DeliveryAttemptBase):
    pass

class DeliveryAttemptResponse(DeliveryAttemptBase):
    attempt_id: int
    timestamp: datetime
    
    model_config = ConfigDict(from_attributes=True)

# ── Dispatch & ML Risk ────────────────────────────────────────────────────────
class DispatchResponse(BaseModel):
    address_id: str
    raw_text: Optional[str] = None
    note: Optional[AccessNoteResponse] = None
    confidence_score: Optional[float] = None
    confidence_label: str

class RiskScoreResponse(BaseModel):
    address_id: str
    raw_text: str
    area: str
    confidence_band: str
    model_risk_score: float
    model_risk_label: str
    model_note: str
    disclaimer: str
    features_used: dict
    model_config = ConfigDict(protected_namespaces=())

class DriverLeaderboardItem(BaseModel):
    driver_id: str
    total_attempts: int
    success_count: int
    failed_count: int
    first_attempt_success_rate: float
    repeat_failure_rate: float
    sla_adherence_rate: float

class AreaBreakdownItem(BaseModel):
    area: str
    total_addresses: int
    total_attempts: int
    success_rate: float
    repeat_failure_rate: float

# ── Explorer / History ────────────────────────────────────────────────────────
class AddressExplorerItem(BaseModel):
    address_id: str
    raw_text: str
    area: str
    confidence_label: str
    confidence_score: float
    note_count: int
    total_attempts: int
    last_confirmed_at: Optional[datetime] = None
    confirmation_count: int
    contradiction_count: int
    sources: List[str]
    possible_duplicate_of: Optional[str] = None  # address_id of flagged pair

class AddressHistoryResponse(BaseModel):
    address_id: str
    raw_text: str
    area: str
    notes: List[AccessNoteResponse]
    attempts: List[DeliveryAttemptResponse]

# ── Edge Case Demo ────────────────────────────────────────────────────────────
class EdgeCaseDemoResponse(BaseModel):
    case_id: int
    title: str
    description: str
    scenario_result: dict

# ── Duplicate merge workflow ──────────────────────────────────────────────────
class DuplicateFlagItem(BaseModel):
    log_id: int
    addr_id_a: str
    addr_id_b: str
    raw_text_a: Optional[str] = None
    raw_text_b: Optional[str] = None
    similarity_score: float
    flagged_at: datetime
    decision: Optional[MergeDecisionEnum] = None
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None
    canonical_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class MergeDecisionRequest(BaseModel):
    decision: MergeDecisionEnum
    decided_by: str
    canonical_id: Optional[str] = None  # required if decision = MERGED

    @field_validator("decided_by")
    @classmethod
    def validate_decided_by(cls, v):
        if not v or not v.strip():
            raise ValueError("decided_by must not be empty")
        return v.strip()

# ── Notification ──────────────────────────────────────────────────────────────
class NotifyRequest(BaseModel):
    address_id: str
    note_id: int
    recipient: Optional[str] = None   # phone / email — optional in simulated mode

class NotifyResponse(BaseModel):
    status: str
    mode: str
    channel: str
    message: str
