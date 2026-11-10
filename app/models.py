from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from app.config import BLOOD_GROUPS, COMPONENT_TYPES

# Auth & User Models
class UserLogin(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=4)

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$")
    role: str = Field(..., pattern="^(admin|staff|hospital|donor)$")

class UserStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(active|inactive)$")

class UserResponse(BaseModel):
    id: int
    username: str
    full_name: str
    email: str
    role: str
    status: str
    created_at: str

# Donor Models
class DonorCreate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    age: int = Field(..., ge=18, le=65)
    gender: str = Field(..., pattern="^(Male|Female|Other)$")
    blood_group: str
    phone: str = Field(..., min_length=7, max_length=20)
    email: Optional[str] = None
    address: Optional[str] = None
    medical_remarks: Optional[str] = None

    @field_validator("blood_group")
    @classmethod
    def validate_blood_group(cls, v):
        if v not in BLOOD_GROUPS:
            raise ValueError(f"Invalid blood group: {v}. Must be one of {BLOOD_GROUPS}")
        return v

class EligibilityCheckRequest(BaseModel):
    weight_kg: float = Field(..., ge=30.0, le=250.0)
    hemoglobin_g_dl: float = Field(..., ge=5.0, le=25.0)
    systolic_bp: int = Field(..., ge=70, le=220)
    diastolic_bp: int = Field(..., ge=40, le=140)
    pulse: int = Field(..., ge=40, le=160)
    days_since_last_donation: Optional[int] = Field(default=999, ge=0)
    medical_flags: Optional[str] = None

class EligibilityResponse(BaseModel):
    donor_id: str
    is_eligible: bool
    rejection_reasons: List[str]
    vitals_summary: Dict[str, Any]

class DonorResponse(BaseModel):
    donor_id: str
    full_name: str
    age: int
    gender: str
    blood_group: str
    phone: str
    email: Optional[str] = None
    address: Optional[str] = None
    medical_remarks: Optional[str] = None
    created_at: str
    donation_count: int = 0
    last_donation_date: Optional[str] = None

# Collection & Unit Models
class CollectionCreate(BaseModel):
    donor_id: str
    blood_group: str
    volume_ml: float = Field(default=450.0, ge=100.0, le=600.0)
    component_type: str = Field(default="Whole Blood")
    collection_date: Optional[date] = None

    @field_validator("blood_group")
    @classmethod
    def validate_group(cls, v):
        if v not in BLOOD_GROUPS:
            raise ValueError(f"Invalid blood group: {v}")
        return v

    @field_validator("component_type")
    @classmethod
    def validate_component(cls, v):
        if v not in COMPONENT_TYPES:
            raise ValueError(f"Invalid component type: {v}")
        return v

class UnitStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(Available|Quarantined|Discarded)$")
    reason: str = Field(..., min_length=3, max_length=255)

class BloodUnitResponse(BaseModel):
    unit_id: str
    collection_id: Optional[str]
    donor_id: str
    blood_group: str
    component_type: str
    volume_ml: float
    collection_date: str
    expiry_date: str
    status: str
    storage_location: str
    days_until_expiry: int
    is_expired: bool

# Request Models
class BloodRequestCreate(BaseModel):
    hospital_name: str = Field(..., min_length=2, max_length=150)
    requester_name: str = Field(..., min_length=2, max_length=100)
    patient_name: str = Field(..., min_length=2, max_length=100)
    patient_blood_group: str
    component_type: str
    quantity: int = Field(..., ge=1, le=20)
    urgency: str = Field(default="Normal", pattern="^(Normal|Urgent|Emergency)$")
    required_date: date

    @field_validator("patient_blood_group")
    @classmethod
    def validate_group(cls, v):
        if v not in BLOOD_GROUPS:
            raise ValueError(f"Invalid blood group: {v}")
        return v

    @field_validator("component_type")
    @classmethod
    def validate_comp(cls, v):
        if v not in COMPONENT_TYPES:
            raise ValueError(f"Invalid component type: {v}")
        return v

class BloodRequestDecision(BaseModel):
    decision: str = Field(..., pattern="^(Approved|Rejected|On_Hold)$")
    reason: str = Field(..., min_length=3, max_length=255)

class BloodRequestResponse(BaseModel):
    request_id: str
    hospital_name: str
    requester_name: str
    patient_name: str
    patient_blood_group: str
    component_type: str
    quantity: int
    urgency: str
    required_date: str
    status: str
    decision_reason: Optional[str]
    decision_by: Optional[str]
    decision_at: Optional[str]
    created_at: str
    allocated_units: List[str] = []

# Allocation & Issue Models
class AllocateRequest(BaseModel):
    request_id: str
    selected_unit_ids: Optional[List[str]] = None  # None indicates auto-FEFO

class IssueRequest(BaseModel):
    request_id: str
    verification_notes: Optional[str] = "Standard crossmatch and identity verified."

class IssueResponse(BaseModel):
    issue_id: str
    request_id: str
    unit_id: str
    hospital_name: str
    patient_name: str
    issuing_staff: str
    issue_timestamp: str
    verification_notes: Optional[str]
