from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, Enum
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

class Address(Base):
    __tablename__ = "addresses"

    address_id = Column(String, primary_key=True, index=True)
    raw_text = Column(String, nullable=False)
    area = Column(String, nullable=False)

    attempts = relationship("DeliveryAttempt", back_populates="address")
    notes = relationship("AccessNote", back_populates="address")

class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    attempt_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    address_id = Column(String, ForeignKey("addresses.address_id"))
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    outcome = Column(Enum(OutcomeEnum), nullable=False)
    failure_reason = Column(Enum(FailureReasonEnum), default=FailureReasonEnum.NONE)
    driver_id = Column(String, nullable=False)
    used_note_id = Column(Integer, ForeignKey("access_notes.note_id"), nullable=True)

    address = relationship("Address", back_populates="attempts")
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

    address = relationship("Address", back_populates="notes")
    uses = relationship("DeliveryAttempt", back_populates="used_note")
