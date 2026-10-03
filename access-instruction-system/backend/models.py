from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, Enum, Boolean
from sqlalchemy.orm import relationship
import enum
import datetime
from .database import Base

class OutcomeEnum(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RTO = "RTO"

class FailureReasonEnum(str, enum.Enum):
    NO_ACCESS = "NO_ACCESS"
    WRONG_ADDRESS = "WRONG_ADDRESS"
    CUSTOMER_UNAVAILABLE = "CUSTOMER_UNAVAILABLE"
    GATE_LOCKED = "GATE_LOCKED"
    NONE = "NONE"

class SourceEnum(str, enum.Enum):
    DRIVER_LOGGED = "DRIVER_LOGGED"
    CUSTOMER_CONFIRMED = "CUSTOMER_CONFIRMED"

class MergeDecisionEnum(str, enum.Enum):
    MERGED = "MERGED"
    KEPT_SEPARATE = "KEPT_SEPARATE"

class Address(Base):
    __tablename__ = "addresses"

    address_id = Column(String, primary_key=True, index=True)
    raw_text = Column(String, nullable=False)
    area = Column(String, nullable=False)
    # If this address was merged into another, canonical_id points to the keeper
    canonical_id = Column(String, ForeignKey("addresses.address_id"), nullable=True)
    is_archived = Column(Boolean, default=False)

    attempts = relationship("DeliveryAttempt", back_populates="address", foreign_keys="DeliveryAttempt.address_id")
    notes = relationship("AccessNote", back_populates="address", foreign_keys="AccessNote.address_id")

class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    attempt_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    address_id = Column(String, ForeignKey("addresses.address_id"))
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    outcome = Column(Enum(OutcomeEnum), nullable=False)
    failure_reason = Column(Enum(FailureReasonEnum), default=FailureReasonEnum.NONE)
    driver_id = Column(String, nullable=False)
    used_note_id = Column(Integer, ForeignKey("access_notes.note_id"), nullable=True)
    promised_slot = Column(String, nullable=True)  # e.g. '10:00-13:00 slot'
    is_within_sla = Column(Boolean, default=True)  # whether delivered within promised window

    address = relationship("Address", back_populates="attempts", foreign_keys=[address_id])
    used_note = relationship("AccessNote", back_populates="uses")

class AccessNote(Base):
    __tablename__ = "access_notes"

    note_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    address_id = Column(String, ForeignKey("addresses.address_id"))
    instruction_text = Column(String, nullable=False)
    source = Column(Enum(SourceEnum), default=SourceEnum.DRIVER_LOGGED)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_confirmed_at = Column(DateTime, default=datetime.datetime.utcnow)
    confirmation_count = Column(Integer, default=0)
    contradiction_count = Column(Integer, default=0)

    address = relationship("Address", back_populates="notes", foreign_keys=[address_id])
    uses = relationship("DeliveryAttempt", back_populates="used_note")

class DuplicateMergeLog(Base):
    """
    Human-in-the-loop merge review log.
    Every flagged pair is recorded here. Merges are NEVER automatic.
    """
    __tablename__ = "duplicate_merge_log"

    log_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    addr_id_a = Column(String, nullable=False)
    addr_id_b = Column(String, nullable=False)
    similarity_score = Column(Float, nullable=False)
    flagged_at = Column(DateTime, default=datetime.datetime.utcnow)
    decision = Column(Enum(MergeDecisionEnum), nullable=True)   # NULL = pending
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(String, nullable=True)  # ops manager ID
    canonical_id = Column(String, nullable=True)  # set only if MERGED

class NotifyLog(Base):
    """Tracks outbound notification attempts (simulated or real)."""
    __tablename__ = "notify_log"

    log_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    address_id = Column(String, nullable=False)
    note_id = Column(Integer, nullable=True)
    channel = Column(String, nullable=False)   # SMS / EMAIL / WHATSAPP / SIMULATED
    mode = Column(String, nullable=False)       # simulated | real
    status = Column(String, nullable=False)     # SENT / FAILED / SIMULATED
    sent_at = Column(DateTime, default=datetime.datetime.utcnow)
    recipient = Column(String, nullable=True)
