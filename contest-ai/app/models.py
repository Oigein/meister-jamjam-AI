from datetime import date
from typing import Literal, Annotated
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Kind = Literal['VALUE', 'HIGH_SCORE', 'SHORT_TERM']

class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Goal(Model):
    targetScore: int | None = Field(None, ge=1)
    description: str | None = Field(None, max_length=100)

class RecommendationRequest(Model):
    major: Literal['BACKEND', 'FRONTEND', 'AI', 'APP', 'EMBEDDED', 'ETC'] | None = None
    techStack: list[Annotated[str, StringConstraints(min_length=1, max_length=30)]] = Field(default_factory=list, max_length=10)
    goal: Goal | None = None
    availableUntil: date | None = None
    types: list[Kind] = Field(default_factory=lambda: ['VALUE', 'HIGH_SCORE', 'SHORT_TERM'], min_length=1, max_length=3)
    includeExamPeriod: bool = False

class ChatRequest(Model):
    conversationId: UUID | None = None
    contestId: int | None = Field(None, gt=0)
    message: str = Field(min_length=1, max_length=1000)

class Guidelines(Model):
    promptGuideline: str = Field(max_length=10000)
    examBufferDays: int = Field(ge=0, le=365)
    version: int = Field(ge=1)

class Choice(BaseModel):
    # Additional provider fields never become authoritative response data.
    contestId: int
    recommendType: Kind
    reason: str = Field(min_length=1, max_length=2000)
    teamTip: str = Field(max_length=1000)

class Choices(BaseModel):
    recommendations: list[Choice] = Field(max_length=100)
