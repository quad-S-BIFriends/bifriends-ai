"""
폴백 데이터.

1) STEP12_FALLBACK_URL: 감정별 step1·2 고정 이미지 URL (정상 생성 시에도 step1·2는 이걸 재사용).
   - URL은 BE가 폴백 12장을 GCS 업로드 후 발급. 아래는 자리표시자.
   - 운영 전 BE가 준 실제 URL로 교체 (또는 .env/config 주입으로 분리 가능).

2) FALLBACK_SCENARIOS: AI 생성 실패 시 통째로 내보낼 감정별 완성 시나리오(텍스트+이미지 URL 전부 포함).
   - 생성 규격 문서의 6개 샘플(기쁨~고마움)을 채워넣는다. 여기서는 구조만 잡고 실제 텍스트는 추후 채움.
   - step3 이미지도 폴백은 고정 URL (실시간 생성 안 함).
"""

from app.schemas.content import Emotion

# 자리표시자 — BE가 GCS 업로드 후 발급한 URL로 교체
_BASE = "https://storage.googleapis.com/bifriends-sel-fallback"

STEP12_FALLBACK_URL: dict[Emotion, dict[str, str]] = {
    Emotion.JOY: {
        "step1": f"{_BASE}/joy/step1.png",
        "step2": f"{_BASE}/joy/step2.png",
    },
    Emotion.SAD: {
        "step1": f"{_BASE}/sad/step1.png",
        "step2": f"{_BASE}/sad/step2.png",
    },
    Emotion.SHY: {
        "step1": f"{_BASE}/shy/step1.png",
        "step2": f"{_BASE}/shy/step2.png",
    },
    Emotion.ANGRY: {
        "step1": f"{_BASE}/angry/step1.png",
        "step2": f"{_BASE}/angry/step2.png",
    },
    Emotion.DISAPPOINTED: {
        "step1": f"{_BASE}/disappointed/step1.png",
        "step2": f"{_BASE}/disappointed/step2.png",
    },
    Emotion.GRATEFUL: {
        "step1": f"{_BASE}/grateful/step1.png",
        "step2": f"{_BASE}/grateful/step2.png",
    },
}

# step3 폴백 컷 이미지 URL (전체 폴백 시나리오에서 사용)
STEP3_FALLBACK_URL: dict[Emotion, list[str]] = {
    e: [f"{_BASE}/{slug}/step3_1.png",
        f"{_BASE}/{slug}/step3_2.png",
        f"{_BASE}/{slug}/step3_3.png"]
    for e, slug in [
        (Emotion.JOY, "joy"), (Emotion.SAD, "sad"), (Emotion.SHY, "shy"),
        (Emotion.ANGRY, "angry"), (Emotion.DISAPPOINTED, "disappointed"),
        (Emotion.GRATEFUL, "grateful"),
    ]
}


def get_step12_urls(emotion: Emotion) -> dict[str, str]:
    return STEP12_FALLBACK_URL[emotion]


def get_step3_fallback_urls(emotion: Emotion) -> list[str]:
    return STEP3_FALLBACK_URL[emotion]


# ---------------------------------------------------------------------------
# 전체 폴백 시나리오 (AI 생성 실패 시 통째로 반환).
# 생성 규격 문서의 6개 샘플 기반. 정상 응답과 100% 동일한 구조로 구성하기 위해
# build_full_fallback()에서 ScenarioResponse로 변환한다.
# step3 이미지는 실시간 생성 안 하고 STEP3_FALLBACK_URL을 쓴다.
#
# 아래 dict는 LLM 텍스트 출력(content_scenario.txt 출력 양식)과 동일한 키를 갖는다.
# 따라서 build_full_fallback은 정상 경로의 assemble_response와 같은 변환을 태운다.
# (여기서는 화남 1개를 완성 예시로 채운다. 나머지 5개는 동일 구조로 채워 넣을 것.)
# ---------------------------------------------------------------------------

FALLBACK_TEXT: dict[Emotion, dict] = {
    Emotion.ANGRY: {
        "situation": "학교 운동장",
        "learned_expression": "열불이 난다",
        "step1": {
            "expression": "열불이 난다",
            "body_sensation": "몸 안에서 뜨거운 게 확 올라오는 것처럼 느껴지고 주먹에 힘이 들어가요.",
            "situation_example": "친구가 내 말을 계속 못 듣고 넘어갈 때 이런 마음이 들 수 있어요.",
        },
        "step2": {
            "visual_clue": "눈썹이 잔뜩 찌푸려져 있고 얼굴이 빨개져 있어요.",
            "choices": [
                {"id": "A", "text": "화남", "is_correct": True,
                 "feedback": "맞아요! 눈썹이 찌푸려지고 얼굴이 빨개진 걸 보면 화난 마음이 느껴져요."},
                {"id": "B", "text": "속상함", "is_correct": False,
                 "feedback": "속상할 때는 눈물이 올라오는 느낌이 들어요. 이 친구는 눈썹에 힘이 들어가 있어 화남에 더 가까워요."},
                {"id": "C", "text": "실망", "is_correct": False,
                 "feedback": "실망할 때는 힘이 빠지는 느낌이에요. 이 친구는 뜨거운 게 올라오는 화남에 더 가까워요."},
            ],
        },
        "step3": {
            "background": "school playground",
            "comic": [
                {"cut": 1, "text": "민이는 친구들과 팀을 나눴어요.", "cast": "main+friend",
                 "scene": "The main character and the friend stand together on a playground, smiling and talking while dividing into teams."},
                {"cut": 2, "text": "민이가 말했는데 친구가 못 듣고 넘어갔어요.", "cast": "main+friend",
                 "scene": "The main character is on the left, speaking with one hand raised toward the friend, mouth open. The friend is on the right, turned away, distracted, not noticing."},
                {"cut": 3, "text": "민이는 몸 안에 열이 확 올라왔어요.", "cast": "main",
                 "scene": "The main character stands alone, clearly angry, eyebrows furrowed, fists clenched, mildly red face, child-friendly not scary."},
            ],
            "choices": [
                {"id": "A", "text": "친구가 민이 말을 듣지 않고 넘어갔어요.", "is_correct": True,
                 "feedback": "맞아요! 말을 해도 친구가 들어주지 않아서 민이는 열불이 났어요."},
                {"id": "B", "text": "친구가 민이를 팀에 불러줬어요.", "is_correct": False,
                 "feedback": "팀에 불러준 건 기분 좋은 일일 수 있어요. 두 번째 그림을 다시 보면 도움이 돼요."},
                {"id": "C", "text": "민이가 게임에서 이겼어요.", "is_correct": False,
                 "feedback": "게임에서 이기면 신나는 마음이 들어요. 어떤 일이 마음을 바꿨는지 다시 볼까요?"},
            ],
        },
        "step4": {
            "leo_intro": "맞아요! 친구가 말을 듣지 않고 넘어가서 민이는 화남을 느꼈어요. 이럴 때 친구는 뭐라고 말해줄까요?",
            "choices": [
                {"id": "A", "text": "미안해, 못 들었어. 다시 말해줄 수 있을까?", "type": "empathetic",
                 "is_correct": True, "feedback": "정말 잘했어요! 사과하고 다시 들으려는 모습에 민이의 화가 풀릴 거예요."},
                {"id": "B", "text": "그냥 넘어가면 되잖아.", "type": "indifferent",
                 "is_correct": False, "feedback": "그냥 넘어가면 민이는 여전히 속상할 수 있어요. 먼저 미안하다고 말해주면 좋아요."},
                {"id": "C", "text": "나 몰라, 다른 애한테 물어봐.", "type": "irrelevant",
                 "is_correct": False, "feedback": "그 말은 민이를 더 속상하게 만들 수 있어요. 용기 내서 먼저 사과해보면 어떨까요?"},
            ],
            "success_message": "정말 멋진 대답이에요! 사과하고 다시 들어주려는 말 한 마디가 친구 사이를 다시 따뜻하게 만들어요.",
        },
    },
    # TODO: 기쁨/속상함/부끄러움/실망/고마움 5개를 같은 구조로 채워넣기 (생성 규격 문서 샘플 사용).
}


def get_fallback_text(emotion: Emotion) -> dict:
    """폴백 텍스트 반환. 해당 감정이 아직 없으면 화남(완성본)으로 안전 대체."""
    return FALLBACK_TEXT.get(emotion, FALLBACK_TEXT[Emotion.ANGRY])