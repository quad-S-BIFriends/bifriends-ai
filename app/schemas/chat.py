from typing import Literal
from pydantic import BaseModel, Field

# BE -> AI 요청
class ChatRequest(BaseModel):
    member_id: int
    nickname: str
    grade: int = Field(ge=3, le=6)
    interests: list[str] = Field(default_factory=list)
    session_id: str
    message: str

# CTA 모델
class StepCTA(BaseModel):
    """ 수학 : 특정 step으로 넘어가는 CTA 모델 """
    type: Literal["navigate_to_step"] = "navigate_to_step"
    label: str
    step_id: int
    cycle_number: int
    subject: Literal["math"] = "math"

class SubjectCTA(BaseModel):
    """국어: 과목 페이지로 이동하는 CTA 모델"""
    type: Literal["navigate_to_subject"] = "navigate_to_subject"
    label: str
    subject: Literal["korean"] = "korean"


# 할 일 
class TodoCreated(BaseModel):
    """AI → BE 응답에 포함되는 등록 결과 (시간 정보 없음)"""
    title: str
    assigned_date: str  # yyyy-MM-dd

# AI -> BE 응답
class ChatResponse(BaseModel):
    message: str
    cta: StepCTA | SubjectCTA | None = None
    todos_created: list[TodoCreated] | None = None