"""
친구랑(EMO) 콘텐츠 생성 스키마.

설계 메모
- step1~4 구조는 생성 규격 문서(Step별 JSON 규격)를 그대로 따른다.
- 이미지 분업 (BE 합의 기준):
    * step1, step2 → 감정별 고정 폴백 URL 재사용 (실시간 생성 X). AI가 image_url을 채워서 응답.
    * step3 3컷 → 실시간 생성. AI가 image_b64(base64)로 채워서 응답 → BE가 GCS 업로드 후 URL 치환.
- 버튼 문구/타입/리워드 등 LLM이 만지면 안 되는 고정값은 코드가 결정론적으로 채운다(스키마는 그 자리만 제공).
- emotion 값은 한국어 6개 Pool 고정. image_prompt 텍스트만 영어.

미정(BE 회신 대기): 최종 URL을 FE로 내려줄 때의 필드명(image_url로 가정).
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ---- 고정 Pool / 상수성 enum ----------------------------------------------

class Emotion(str, Enum):
    JOY = "기쁨"
    SAD = "속상함"
    SHY = "부끄러움"
    ANGRY = "화남"
    DISAPPOINTED = "실망"
    GRATEFUL = "고마움"


class ChoiceType(str, Enum):
    """Step4 선택지 유형."""
    EMPATHETIC = "empathetic"
    INDIFFERENT = "indifferent"
    IRRELEVANT = "irrelevant"


# ---- 요청 -----------------------------------------------------------------

class ScenarioRequest(BaseModel):
    """
    BE → AI 시나리오 생성 요청.
    member 프로필(닉네임/관심사)은 BE가 body로 전달.
    learned_expressions: 이미 학습한 표현(중복 제외용).
    emotion이 None이면 코드가 Pool에서 선택(중복 회피).
    """
    member_id: int
    nickname: str
    interests: list[str] = Field(default_factory=list)
    learned_expressions: list[str] = Field(default_factory=list)
    emotion: Optional[Emotion] = None  # 미지정 시 코드가 선택


# ---- 공통 하위 구조 --------------------------------------------------------

class Choice(BaseModel):
    """Step2/3 선택지 (감정·원인 선택)."""
    id: str                      # "A" | "B" | "C"
    text: str
    is_correct: bool
    feedback: str


class Step4Choice(BaseModel):
    """Step4 선택지 (반응 선택). type 필드가 추가됨."""
    id: str
    text: str
    type: ChoiceType
    is_correct: bool
    feedback: str


class ComicCut(BaseModel):
    """
    Step3 3컷 만화의 한 컷.
    이미지 전달 방식:
      - 정상 생성: image_b64에 base64 (BE가 GCS 업로드 후 image_url 치환)
      - 폴백:      image_url에 고정 URL (생성 안 함)
    둘 중 하나만 채워지며, FE는 image_url이 있으면 그것을, 없으면 b64를 쓴다.
    image_prompt는 항상 기록용으로 채워진다.
    """
    cut: int                          # 1 | 2 | 3
    text: str                         # 15~25자 내외 한국어 문장
    image_prompt: str                 # 영문, 코드가 조립한 최종본 (기록용)
    image_b64: Optional[str] = None   # 정상 생성 결과(base64)
    image_url: Optional[str] = None   # 폴백 고정 URL (또는 BE 업로드 후 치환값)


class Reward(BaseModel):
    type: str = "grass"
    amount: int = 10


# ---- Step 구조 ------------------------------------------------------------

class Step1(BaseModel):
    """오늘의 표현 배우기. 이미지는 감정별 고정 폴백 URL."""
    title: str = "오늘의 표현"
    expression: str
    emotion: Emotion
    body_sensation: str
    situation_example: str
    image_url: Optional[str] = None   # 감정별 고정 폴백(상반신). AI가 채움.
    next_button_text: str = "이해했어!"


class Step2(BaseModel):
    """어떤 기분일까요? 이미지는 감정별 고정 폴백 URL."""
    title: str = "어떤 기분일까요?"
    visual_clue: str
    question: str = "이 친구는 어떤 기분일까요?"
    choices: list[Choice]
    image_url: Optional[str] = None   # 감정별 고정 폴백(얼굴 클로즈업). AI가 채움.
    retry_message: str = "다시 한 번 골라볼까요?"
    next_button_text: str = "이 마음일 것 같아!"   # 확정 문구 (명세 EMO-11 일치)


class Step3(BaseModel):
    """3컷 만화 원인 찾기. 3컷 이미지는 실시간 생성(b64)."""
    title: str = "이야기를 봐요"
    comic: list[ComicCut]             # 정확히 3컷
    question: str = "어떤 일이 있어서 이런 기분이 들었을까요?"
    choices: list[Choice]
    retry_message: str = "그림을 다시 보고 골라볼까요?"
    next_button_text: str = "다음 이야기 보기"


class Step4(BaseModel):
    """이렇게 말하고 싶어! 이미지 없음."""
    title: str = "뭐라고 말해줄까요?"
    leo_intro: str
    question: str = "친구에게 어떤 말을 해주면 좋을까요?"
    choices: list[Step4Choice]
    retry_message: str = "친구 마음을 생각하면서 다시 골라볼까요?"
    success_message: str
    reward: Reward = Field(default_factory=Reward)
    complete_button_text: str = "친구 마음 알아보기 완료!"


class MindSteps(BaseModel):
    step1: Step1
    step2: Step2
    step3: Step3
    step4: Step4


# ---- 응답 -----------------------------------------------------------------

class ScenarioResponse(BaseModel):
    """
    AI → BE 응답.
    set_id/emotion/situation/learned_expression은 저장(mindSessions)용 메타.
    is_fallback: 전체 폴백 시나리오로 응답했는지 표시(BE/모니터링용).
    """
    set_id: str
    emotion: Emotion
    situation: str
    learned_expression: str
    steps: MindSteps
    is_fallback: bool = False