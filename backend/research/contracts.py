from enum import StrEnum
from typing import Any, ClassVar, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from models.foods import normalize_food_text
from research.evidence import audit
from schemas.foods import FoodCreate, FoodRead
from schemas.exercises import ExerciseCreate, ExerciseRead

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Intent(StrEnum):
    LOG_FOOD = 'LOG_FOOD'
    LOG_EXERCISE = 'LOG_EXERCISE'
    FOOD_KNOWLEDGE_QA = 'FOOD_KNOWLEDGE_QA'
    SPORTS_KNOWLEDGE_QA = 'SPORTS_KNOWLEDGE_QA'
    EXERCISE_TECHNIQUE_QA = 'EXERCISE_TECHNIQUE_QA'
    TRAINING_PLAN = 'TRAINING_PLAN'
    DEEP_RESEARCH = 'DEEP_RESEARCH'
    GENERAL_CHAT = 'GENERAL_CHAT'

QA_INTENTS = {i.value for i in Intent} - {'LOG_FOOD', 'LOG_EXERCISE', 'GENERAL_CHAT'}

class ResearchStatus(StrEnum):
    COMPLETED = 'COMPLETED'
    INSUFFICIENT_EVIDENCE = 'INSUFFICIENT_EVIDENCE'
    NEEDS_USER_INPUT = 'NEEDS_USER_INPUT'
    NEEDS_REVIEW = 'NEEDS_REVIEW'
    FAILED = 'FAILED'

class EvidenceClaim(StrictModel):
    claim: str = Field(min_length=1, max_length=2000)
    field: str = Field(min_length=1, max_length=200, description='Payload field path this claim supports, e.g. configuration.default_met')
    source_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=800)
    applicable: bool
    # The model's guess; verified claims carry the source registry's tier instead (research/sources.py).
    authority: Literal['primary', 'professional', 'secondary', 'unknown']
    published_at: str | None = None
    conflict: bool = False

class ResearchLimits(StrictModel):
    rounds: int = 2
    search_calls: int = 3
    documents: int = 6
    web_calls: int = 8
    llm_calls: int = 3
    deadline_seconds: int = 60

class ResearchPlan(StrictModel):
    intent: str
    target: str = Field(min_length=1, max_length=180)
    required_fields: list[str] = Field(default_factory=list, max_length=30)
    queries: list[str] = Field(min_length=1, max_length=3)
    preferred_sources: list[str] = Field(default_factory=list,max_length=10)
    budget: ResearchLimits = Field(default_factory=ResearchLimits)
    confirmation_required: bool = False
    output_schema: str
    # Existing records a requested new variant must be distinguishable from.
    distinct_from: list[str] = Field(default_factory=list, max_length=5)

class ResearchDraft(StrictModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    claims: list[EvidenceClaim] = Field(default_factory=list, max_length=30)
    missing_fields: list[str] = Field(default_factory=list, max_length=30)
    conflicts: list[str] = Field(default_factory=list, max_length=20)
    sufficient: bool = False

class ResearchResult(StrictModel):
    schema_version: int = 2
    status: ResearchStatus
    claims: list[EvidenceClaim] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    error_code: str | None = None

class ResolveQuery(StrictModel):
    query: str = Field(min_length=1, max_length=180)

class SourceReference(StrictModel):
    source_id: str = Field(min_length=1,max_length=2048)
    url: str = Field(max_length=2048)
    title: str = Field(max_length=500)
    retrieved_at: str | None = Field(default=None,max_length=64)

class Attestation(StrictModel):
    """HMAC of the research service over the immutable research content (research/attestation.py)."""
    version: int = Field(ge=1)
    key_id: str = Field(min_length=1, max_length=64)
    issued_at: str = Field(min_length=1, max_length=64)
    signature: str = Field(pattern=r'^[0-9a-f]{64}$')

class Finalization(StrictModel):
    domain: ClassVar[str]
    candidate_id: UUID
    candidate_revision: int = Field(ge=1)
    query: str = Field(min_length=1, max_length=180)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    evidence: list[EvidenceClaim] = Field(min_length=1, max_length=30)
    sources: list[SourceReference] = Field(min_length=1, max_length=6)
    resolution: Literal['create', 'reuse', 'create_distinct'] = 'create'
    # Fingerprints of the resolver results for the query and for payload.name_vi the user decided on.
    expected_match_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    expected_name_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    existing_id: UUID | None = None
    expected_existing_version: int | None = Field(default=None, ge=1)
    # Optional in the contract so the research service can build the command before signing;
    # the finalization API refuses a command without a valid attestation.
    attestation: Attestation | None = None

    @model_validator(mode='after')
    def reuse_requires_version(self):
        if {e.source_id for e in self.evidence} - {s.source_id for s in self.sources}:
            raise ValueError('Evidence source is absent')
        if any(e.conflict or not e.applicable for e in self.evidence):
            raise ValueError('Unresolved evidence cannot be finalized')
        if self.resolution == 'reuse' and (not self.existing_id or not self.expected_existing_version):
            raise ValueError('reuse requires an ID and version')
        if self.resolution != 'reuse' and (self.existing_id or self.expected_existing_version):
            raise ValueError('Only reuse accepts an existing record')
        # The research query is the only alias the flow proposes; anything else is unreviewed.
        if any(normalize_food_text(a) != normalize_food_text(self.query) for a in self.aliases):
            raise ValueError('Invalid alias')
        return self

    @model_validator(mode='after')
    def evidence_covers_payload(self):
        urls = {s.source_id: s.url for s in self.sources}
        payload = self.payload.model_dump(mode='json')
        audited, missing, cleared = audit(self.domain, payload, self.evidence, lambda source_id: urls.get(source_id, ''))
        if missing or audited != payload:
            raise ValueError('Payload values lack field evidence: ' + (', '.join(missing + cleared) or 'derived fields'))
        return self

class FoodFinalization(Finalization):
    domain: ClassVar[str] = 'foods'
    payload: FoodCreate

class ExerciseFinalization(Finalization):
    domain: ClassVar[str] = 'exercises'
    payload: ExerciseCreate

class Provenance(StrictModel):
    """Present only when the research service's attestation verified."""
    research_verified: bool
    candidate_id: UUID
    key_id: str
    attested_at: str

class FoodFinalizationResult(StrictModel):
    outcome: Literal['created', 'reused']
    record: FoodRead
    provenance: Provenance

class ExerciseFinalizationResult(StrictModel):
    outcome: Literal['created', 'reused']
    record: ExerciseRead
    provenance: Provenance
