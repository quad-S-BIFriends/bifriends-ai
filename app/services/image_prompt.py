"""
이미지 프롬프트 조립 (LLM 미사용).

원칙
- LLM이 캐릭터 외형을 지어내면 매 컷 캐릭터가 흔들린다 → 외형은 코드 상수로 고정 주입.
- LLM은 "이 컷의 장면(scene)"만 생성. 최종 image_prompt = 코드가 조립.
- step1·2 배경 = 흰색 고정. step3 컷1 = 배경 명시, 컷2·3 = 직전과 same.
- step3 배경 컷에는 full-bleed 키워드로 흰 테두리 방지.
- 감정 → 고정 주인공(성별) 매핑. step1·2 폴백과 step3 주인공이 같은 아이여야 함.

미정(BE 회신 대기): 감정→성별 매핑은 폴백 제작 배분 기준으로 가정.
"""

from app.schemas.content import Emotion


# ---- 감정 → 고정 주인공 성별 (폴백 12장 제작 배분과 일치) ------------------
EMOTION_GENDER: dict[Emotion, str] = {
    Emotion.JOY: "boy",
    Emotion.SHY: "boy",
    Emotion.ANGRY: "boy",
    Emotion.SAD: "girl",
    Emotion.DISAPPOINTED: "girl",
    Emotion.GRATEFUL: "girl",
}

# ---- 캐릭터 시트 (앵커 이미지와 동일한 외형 기술) --------------------------
MAIN_CHARACTER: dict[str, str] = {
    "boy": (
        "the main character is a boy with short dark brown hair, wearing a light "
        "blue hoodie, dark navy pants,white socks, white sneakers"
    ),
    "girl": (
        "the main character is a girl with long brown hair and small pink ribbons, "
        "wearing a yellow t-shirt, light blue skirt, white socks, white sneakers"
    ),
}

# 핵심 조연(친구) 외형. 한 세트 내내 동일. 군중은 외형 고정 안 하고 generic 처리.
FRIEND_CHARACTER = (
    "the friend character has a black bob with a blue hairband, "
    "a green t-shirt and a purple skirt"
)

# ---- 공통 꼬리표 ----------------------------------------------------------
STYLE_TAIL = (
    "Soft flat children's storybook illustration, clean rounded outlines, "
    "soft pastel colors. No text anywhere in the image. "
    "Child-friendly, gentle expressions, never scary."
)
CONSISTENCY_TAIL = (
    "Keep the main character's face, hair, and outfit identical to the "
    "reference/previous image."
)
ASPECT = "Square 1:1 aspect ratio."

# step1·2 전용: 흰 배경 고정
WHITE_BG = "Plain solid white background, centered composition."

# step3 전용: 흰 테두리 방지 full-bleed
def fullbleed(background: str) -> str:
    return (
        f"Full-bleed composition, the {background} fills the entire frame "
        f"with no white borders or margins, edge-to-edge background."
    )


def assemble_step3_prompt(
    *,
    gender: str,
    scene: str,
    cut: int,
    background: str,
    include_friend: bool,
) -> str:
    """
    step3 한 컷의 최종 image_prompt 조립.

    gender        : "boy" | "girl"
    scene         : LLM이 생성한 이 컷의 행동/표정/구도 묘사(영문)
    cut           : 1 | 2 | 3 (컷1은 배경 명시, 컷2·3은 same)
    background    : 컷1에서 정한 배경 키워드 (예: "school classroom")
    include_friend: 이 컷에 핵심 조연이 등장하는지 (컷별 캐스팅 결과)
    """
    parts: list[str] = [MAIN_CHARACTER[gender]]
    if include_friend:
        parts.append(FRIEND_CHARACTER)

    parts.append(scene)

    if cut == 1:
        parts.append(f"Background: a simple {background}.")
        parts.append(fullbleed(background))
    else:
        parts.append(f"Same {background} background as the previous image.")
        parts.append(fullbleed(background))

    parts.append(CONSISTENCY_TAIL)
    parts.append(STYLE_TAIL)
    parts.append(ASPECT)
    return " ".join(parts)


def assemble_anchor_instruction(gender: str) -> str:
    """
    step3 첫 컷 생성 시 앵커 이미지와 함께 주는 캐릭터 고정 지시.
    (앵커 이미지 자체는 agent/runner 단에서 input으로 첨부)
    """
    return (
        f"Use the attached image as the exact character and art-style reference. "
        f"{MAIN_CHARACTER[gender]}. {STYLE_TAIL} {ASPECT}"
    )