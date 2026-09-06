from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List
from .models import OutcomeEnum, FailureReasonEnum, SourceEnum

class AddressBase(BaseModel):
    address_id: str
    raw_text: str
    area: str

class AddressCreate(AddressBase):
    pass

class AddressResponse(AddressBase):
    model_config = ConfigDict(from_attributes=True)

class AccessNoteBase(BaseModel):
    instruction_text: str

class AccessNoteCreate(AccessNoteBase):
    address_id: str
    source: SourceEnum = SourceEnum.DRIVER_LOGGED

class AccessNoteResponse(AccessNoteBase):
    note_id: int
    address_id: str
    source: SourceEnum
    created_at: datetime
    last_confirmed_at: datetime
    confirmation_count: int
    contradiction_count: int
    
    model_config = ConfigDict(from_attributes=True)

class DeliveryAttemptBase(BaseModel):
    address_id: str
    outcome: OutcomeEnum
    failure_reason: Optional[FailureReasonEnum] = FailureReasonEnum.NONE
    driver_id: str
    used_note_id: Optional[int] = None

class DeliveryAttemptCreate(DeliveryAttemptBase):
    pass

class DeliveryAttemptResponse(DeliveryAttemptBase):
    attempt_id: int
    timestamp: datetime
    
    model_config = ConfigDict(from_attributes=True)

class DispatchResponse(BaseModel):
    address_id: str
    note: Optional[AccessNoteResponse] = None
    confidence_score: Optional[float] = None
    confidence_label: str

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

class AddressHistoryResponse(BaseModel):
    address_id: str
    raw_text: str
    area: str
    notes: List[AccessNoteResponse]
    attempts: List[DeliveryAttemptResponse]

class EdgeCaseDemoResponse(BaseModel):
    case_id: int
    title: str
    description: str
    scenario_result: dict
