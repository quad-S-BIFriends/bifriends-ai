"""
친구랑(SEL) 시나리오 빌더 — 오케스트레이션.

분업 흐름 (각 단계가 한 가지 일만):
  1) generate_scenario_text()   : 호출1. 텍스트 LLM이 텍스트 + step3 scene/cast만 생성 (JSON).
  2) build_step3_prompts()      : 순수 코드. scene+캐스팅 → 최종 image_prompt 조립 (image_prompt.py).
  3) generate_step3_images()    : 호출2. 이미지 모델이 step3 3컷만 멀티턴 생성 (앵커 첨부).
  4) assemble_response()        : 순수 코드. step1·2 폴백 URL 주입 + 고정값 채움 → ScenarioResponse.
  실패 시 → full fallback 시나리오로 대체.

LLM/이미지 모델 실제 호출부는 agent_runner/이미지 클라이언트에 위임(여기서는 인터페이스로 받음).
"""

import json
import logging
import uuid
from typing import Optional

from app.schemas.content import (
    Emotion, ScenarioRequest, ScenarioResponse, MindSteps,
    Step1, Step2, Step3, Step4, Choice, Step4Choice, ComicCut, Reward, ChoiceType,
)
from app.services.image_prompt import (
    EMOTION_GENDER, assemble_step3_prompt, assemble_anchor_instruction,
)
from app.services.content_fallback import get_step12_urls

logger = logging.getLogger(__name__)


# ---- 코드펜스 제거 + JSON 파싱 (프로젝트 공통 패턴) ------------------------

def _parse_llm_json(raw: str) -> dict:
    """LLM 출력에서 ```json 펜스 제거 후 파싱. 실패 시 ValueError."""
    s = raw.strip()
    if s.startswith("```"):
        # ```json ... ``` 또는 ``` ... ```
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    s = s.strip().strip("`").strip()
    return json.loads(s)


# ---- 2) image_prompt 조립 (순수 코드) -------------------------------------

def build_step3_prompts(emotion: Emotion, step3_text: dict) -> list[str]:
    """LLM이 준 step3(background, comic[].scene/cast) → 컷별 최종 image_prompt."""
    gender = EMOTION_GENDER[emotion]
    background = step3_text["background"]
    prompts: list[str] = []
    for cut_obj in step3_text["comic"]:
        include_friend = cut_obj.get("cast", "main") in ("main+friend",)
        prompts.append(
            assemble_step3_prompt(
                gender=gender,
                scene=cut_obj["scene"],
                cut=cut_obj["cut"],
                background=background,
                include_friend=include_friend,
            )
        )
    return prompts


# ---- 4) 응답 조립 (순수 코드, 고정값 주입) ---------------------------------

_VALID_STEP4_TYPES = {"empathetic", "indifferent", "irrelevant"}


def _coerce_step4_choice(c: dict) -> dict:
    """
    LLM이 step4 choice의 type을 허용 외 값(예: 'pressuring')으로 줄 때 방어.
    - is_correct=True  → 정답은 항상 공감(empathetic)
    - is_correct=False 이고 허용 외 type → 'indifferent'로 안전 보정
    (정상적으로 허용된 값이면 그대로 둔다.)
    """
    c = dict(c)
    t = c.get("type")
    if c.get("is_correct"):
        c["type"] = "empathetic"
    elif t not in _VALID_STEP4_TYPES:
        c["type"] = "indifferent"
    return c


def assemble_response(
    *,
    emotion: Emotion,
    text: dict,
    step3_prompts: list[str],
    step3_images_b64: list[Optional[str]],
    is_fallback: bool = False,
) -> ScenarioResponse:
    """텍스트 + 조립된 프롬프트 + 생성 이미지 + step1·2 폴백 URL → 최종 응답."""
    step12 = get_step12_urls(emotion)

    s1 = Step1(
        expression=text["step1"]["expression"],
        emotion=emotion,
        body_sensation=text["step1"]["body_sensation"],
        situation_example=text["step1"]["situation_example"],
        image_url=step12["step1"],
    )
    s2 = Step2(
        visual_clue=text["step2"]["visual_clue"],
        choices=[Choice(**c) for c in text["step2"]["choices"]],
        image_url=step12["step2"],
    )
    comic = [
        ComicCut(
            cut=cut_obj["cut"],
            text=cut_obj["text"],
            image_prompt=step3_prompts[i],
            image_b64=step3_images_b64[i],
        )
        for i, cut_obj in enumerate(text["step3"]["comic"])
    ]
    s3 = Step3(
        comic=comic,
        choices=[Choice(**c) for c in text["step3"]["choices"]],
    )
    s4 = Step4(
        leo_intro=text["step4"]["leo_intro"],
        choices=[Step4Choice(**_coerce_step4_choice(c)) for c in text["step4"]["choices"]],
        success_message=text["step4"]["success_message"],
        reward=Reward(),  # 고정값
    )
    return ScenarioResponse(
        set_id=f"mindset_{uuid.uuid4().hex[:12]}",
        emotion=emotion,
        situation=text["situation"],
        learned_expression=text["learned_expression"],
        steps=MindSteps(step1=s1, step2=s2, step3=s3, step4=s4),
        is_fallback=is_fallback,
    )


# ---- 오케스트레이션 -------------------------------------------------------

async def build_scenario(
    req: ScenarioRequest,
    *,
    text_generator,   # async (prompt_vars) -> raw_json_str  (호출1, agent_runner 위임)
    image_generator,  # async (anchor_instr, prompts, gender) -> list[b64|None] (호출2)
    pick_emotion,     # (learned) -> Emotion  (중복 회피 선택; 코드/간단 로직)
) -> ScenarioResponse:
    """전체 흐름. 각 단계 실패 시 full fallback으로 안전 복귀."""
    emotion = req.emotion or pick_emotion(req.learned_expressions)

    try:
        # 1) 텍스트 생성 (호출1)
        raw = await text_generator(
            emotion=emotion.value,
            nickname=req.nickname,
            interests=req.interests,
            learned_expressions=req.learned_expressions,
        )
        text = _parse_llm_json(raw)

        # 2) image_prompt 조립 (코드)
        step3_prompts = build_step3_prompts(emotion, text["step3"])

        # 3) step3 이미지 3장 생성 (호출2, 멀티턴)
        anchor_instr = assemble_anchor_instruction(EMOTION_GENDER[emotion])
        images_b64 = await image_generator(
            anchor_instruction=anchor_instr,
            prompts=step3_prompts,
            gender=EMOTION_GENDER[emotion],
        )
        if not images_b64 or any(b is None for b in images_b64):
            raise RuntimeError("step3 image generation incomplete")

        # 4) 응답 조립 (코드)
        return assemble_response(
            emotion=emotion,
            text=text,
            step3_prompts=step3_prompts,
            step3_images_b64=images_b64,
        )

    except Exception as e:
        logger.warning("SEL scenario generation failed (%s); using full fallback", e)
        return build_full_fallback(emotion)


# ---- full fallback (생성 실패 시) -----------------------------------------

def build_full_fallback(emotion: Emotion) -> ScenarioResponse:
    """
    AI 생성 실패 시 사전 저장 시나리오로 대체.
    핵심: 정상 경로와 '완전히 동일한' ScenarioResponse 구조로 반환한다
    (BE/FE가 폴백 여부와 무관하게 같은 양식을 받도록). is_fallback=True로만 구분.

    - 텍스트: content_fallback.FALLBACK_TEXT (생성 규격 문서 샘플)
    - step3 이미지: 실시간 생성 안 함 → ComicCut.image_url에 STEP3_FALLBACK_URL 주입.
      (정상은 image_b64, 폴백은 image_url — FE는 url 우선 사용)
    """
    from app.services.content_fallback import get_fallback_text, get_step3_fallback_urls

    text = get_fallback_text(emotion)
    # 폴백은 step3 이미지를 실시간 생성하지 않으므로 image_prompt(scene 조립)가 불필요.
    # 컷 수만큼 빈 prompt 자리만 둔다(기록용 필드 유지).
    cut_count = len(text["step3"]["comic"])
    step3_prompts = [""] * cut_count

    resp = assemble_response(
        emotion=emotion,
        text=text,
        step3_prompts=step3_prompts,
        step3_images_b64=[None] * cut_count,
        is_fallback=True,
    )
    # 폴백 step3 컷 이미지는 고정 URL을 image_url에 주입
    step3_urls = get_step3_fallback_urls(emotion)
    for i, cut in enumerate(resp.steps.step3.comic):
        cut.image_url = step3_urls[i]
    return resp