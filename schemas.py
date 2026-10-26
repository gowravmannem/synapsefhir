from pydantic import BaseModel, Field, field_validator
from typing import List, Literal, Optional

class ExtractedClinicalEntity(BaseModel):
    resource_id: str = Field(description="Bare FHIR resource id exactly as it appears in the bundle (e.g., 'obs-egfr-201')")
    resource_type: str = Field(description="Condition, Observation, MedicationRequest, DiagnosticReport")
    clinical_name: str = Field(description="Standardized name of the condition, lab, or medication")
    date_recorded: Optional[str] = Field(default=None, description="ISO date string")
    status: Optional[str] = Field(default="active", description="active, resolved, preliminary, final")
    value_or_dose: Optional[str] = Field(default=None, description="Lab value with units or medication dosage")

class FastTriageResult(BaseModel):
    patient_id: str
    suspected_specialty: str = Field(description="e.g., Nephrology, Cardiology, Endocrinology")
    primary_referral_reason: str = Field(description="Primary clinical indication justifying referral")
    pertinent_entities: List[ExtractedClinicalEntity] = Field(description="Filtered list of clinically relevant resources")
    guideline_search_query: str = Field(description="Targeted query for clinical society guidelines")
    payer_search_query: Optional[str] = Field(default=None, description="Targeted query for insurer clinical policies on this referral and its workup")

class GuidelineCheckItem(BaseModel):
    criterion: str = Field(description="Mandatory preliminary test or lab according to guidelines")
    status: Literal["SATISFIED", "MISSING", "OUTDATED"]
    supporting_resource_id: Optional[str] = Field(default=None, description="Source FHIR resource id if SATISFIED or OUTDATED")
    clinical_note: str = Field(description="Evaluation rationale")
    basis: Literal["CLINICAL", "PAYER", "BOTH"] = Field(default="CLINICAL", description="Whether the requirement comes from the clinical guideline, the payer policy, or both")

    @field_validator("status", "basis", mode="before")
    @classmethod
    def _upper(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

class ReferralClaim(BaseModel):
    claim_text: str = Field(description="Verifiable factual clinical assertion")
    citation_ids: List[str] = Field(description="Bare FHIR resource ids directly proving this assertion")

class ServiceRequestDraft(BaseModel):
    display: str = Field(description="Diagnostic to order, e.g. 'Renal ultrasound'")
    addresses_criterion: str = Field(description="The exact 'criterion' text from guideline_audit that this order closes")
    rationale: str = Field(description="Why this order is needed before the specialist consult")

class FinalReferralPackage(BaseModel):
    specialty: str
    urgency_level: str = Field(description="Routine, Urgent, Stat")
    patient_summary: List[ReferralClaim] = Field(description="Clinical statements with provenance links")
    guideline_audit: List[GuidelineCheckItem] = Field(description="Diagnostic gap checklist against guidelines")
    contraindications_and_alerts: List[str] = Field(description="Drug conflicts, lab abnormalities, or critical warnings")
    generated_service_requests: List[ServiceRequestDraft] = Field(description="One order per MISSING or OUTDATED audit item")

class OrderDecision(BaseModel):
    order_id: str
    decision: Literal["KEEP", "CANCEL"]
    evidence_resource_id: Optional[str] = Field(default=None, description="Id of the new or changed resource that makes the order redundant (required for CANCEL)")
    rationale: str

    @field_validator("decision", mode="before")
    @classmethod
    def _upper(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

class ReconciliationResult(BaseModel):
    decisions: List[OrderDecision]
    new_alerts: List[str] = Field(default_factory=list, description="New safety alerts raised by the changed resources, if any")
