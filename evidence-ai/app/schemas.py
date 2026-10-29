from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class DocumentType(str, Enum):
    CERTIFICATE = 'CERTIFICATE'
    AWARD = 'AWARD'
    ACTIVITY = 'ACTIVITY'
    LANGUAGE = 'LANGUAGE'
    UNKNOWN = 'UNKNOWN'

class ScoreType(str, Enum):
    JOB_BASIC = 'JOB_BASIC'
    MAJOR_SKILL = 'MAJOR_SKILL'
    CHARACTER_JOB_ETHIC = 'CHARACTER_JOB_ETHIC'
    HUMANITIES_LITERACY = 'HUMANITIES_LITERACY'
    FOREIGN_LANGUAGE = 'FOREIGN_LANGUAGE'

class Extraction(StrictModel):
    """Only document facts and rule references; model never chooses the points."""
    document_type: DocumentType
    title: str | None
    recipient_name: str | None
    issuer: str | None
    issued_date: str | None
    award: str | None
    extracted_text: str
    candidate_rule_id: str | None
    evidence_quote: str | None
    confidence: float = Field(ge=0, le=1)
    uncertainties: list[str]

class Rule(StrictModel):
    id: str
    score_type: ScoreType
    item: str
    document_type: DocumentType
    title_keywords: list[str] = Field(min_length=1)
    points: int = Field(ge=0)
    max_points: int = Field(ge=0)
    required_fields: list[Literal['recipient_name','issuer','issued_date','title','award']]
    example_only: bool
    required_text_keywords: list[str] = Field(default_factory=list)
    issuer_keywords: list[str] = Field(default_factory=list)
    source_section: str | None = None
    review_checks: list[str] = Field(default_factory=list)

class Ruleset(StrictModel):
    certificate_keywords: list[str] = Field(default_factory=list)
    academic_year: int | None = None
    student_grade: int | None = None
    source_document: str | None = None
    version: str
    description: str
    rules: list[Rule]

class AnalysisContext(StrictModel):
    expected_name: str | None = Field(default=None, max_length=50)
    known_document_hashes: list[str] = Field(default_factory=list, max_length=100)

class Recommendation(StrictModel):
    rule_id: str
    score_type: ScoreType
    item: str
    proposed_points: int
    max_points: int
    example_only: bool
    reason: str

class DocumentSummary(StrictModel):
    document_type: DocumentType
    title: str | None
    recipient_name: str | None
    issuer: str | None
    issued_date: str | None
    award: str | None

class ScoreSuggestion(StrictModel):
    score_type: ScoreType
    item: str
    points: int = Field(ge=0)
    example_only: bool

class AnalysisResponse(StrictModel):
    is_recognized_certificate: bool
    document: DocumentSummary
    recommendation: ScoreSuggestion | None
    messages: list[str]
    requires_teacher_approval: Literal[True] = True
