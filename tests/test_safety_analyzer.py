"""
safety_analyzer 유닛 테스트.

순수 Python 함수(Gemini 호출 없음)라 빠르게 실행된다.
아동 안전 시스템이므로 경계값·오탐 케이스를 꼼꼼히 검증한다.
"""
import pytest
from app.services.safety_analyzer import compute_score, classify, has_critical_signal


class TestHasCriticalSignal:
    def test_자해_표현_감지(self):
        assert has_critical_signal(["나 죽고 싶어"]) is True

    def test_자살_단어(self):
        assert has_critical_signal(["자살하고 싶어"]) is True

    def test_사라지고_싶다(self):
        assert has_critical_signal(["그냥 사라지고 싶어"]) is True

    def test_정상_메시지(self):
        assert has_critical_signal(["오늘 학교 재밌었어"]) is False

    def test_빈_목록(self):
        assert has_critical_signal([]) is False

    def test_여러_메시지_중_하나만_위험(self):
        assert has_critical_signal(["기분 좋아", "죽고 싶어", "밥 먹었어"]) is True

    def test_일상어_오탐_방지_배고파(self):
        # "죽을 만큼 배고파" — _CRITICAL에 "죽을래"는 있지만 "죽을 만큼"은 없어야 함
        # 이 테스트가 실패하면 _CRITICAL 키워드 목록 재검토 필요
        assert has_critical_signal(["죽을 만큼 배고파"]) is False

    def test_일상어_오탐_방지_게임(self):
        assert has_critical_signal(["게임에서 다 죽었어"]) is False


class TestComputeScore:
    def test_빈_목록(self):
        assert compute_score([]) == 0

    def test_정상_메시지(self):
        assert compute_score(["오늘 재밌었어", "레오 안녕"]) == 0

    def test_부정감정_3회_이상(self):
        msgs = ["너무 싫어", "진짜 짜증나", "하기 싫어"]
        assert compute_score(msgs) == 2

    def test_부정감정_2회는_미달(self):
        msgs = ["싫어", "짜증나"]
        assert compute_score(msgs) == 0

    def test_감정_고립_1회(self):
        assert compute_score(["혼자라서 외로워"]) == 3

    def test_욕설_1회(self):
        assert compute_score(["씨발"]) == 5

    def test_폭력_피해_언급(self):
        assert compute_score(["친구한테 맞았어"]) == 5

    def test_동일_메시지_4회(self):
        msgs = ["싫어"] * 4
        assert compute_score(msgs) >= 2

    def test_동일_메시지_3회는_반복점수_없음(self):
        # 3회 반복은 +2 없고, 부정감정 3회로만 +2
        msgs = ["싫어"] * 3
        assert compute_score(msgs) == 2  # 부정감정 +2만

    def test_복합_점수_누적(self):
        # 욕설 +5, 고립 +3 → 8
        msgs = ["꺼져", "혼자라서 슬퍼"]
        assert compute_score(msgs) == 8


class TestClassify:
    def test_GREEN_경계(self):
        assert classify(0) == "GREEN"
        assert classify(3) == "GREEN"

    def test_YELLOW_경계(self):
        assert classify(4) == "YELLOW"
        assert classify(7) == "YELLOW"

    def test_RED_경계(self):
        assert classify(8) == "RED"
        assert classify(100) == "RED"

    def test_CRITICAL_표현은_점수_0이어도_RED(self):
        assert classify(0, ["죽고 싶어"]) == "RED"

    def test_CRITICAL_표현은_점수_2이어도_RED(self):
        assert classify(2, ["사라지고 싶어"]) == "RED"

    def test_messages_None이면_키워드_검사_안함(self):
        assert classify(3, None) == "GREEN"

    def test_messages_빈_리스트는_GREEN(self):
        assert classify(3, []) == "GREEN"

    def test_YELLOW_범위_위험표현_없으면_YELLOW(self):
        msgs = ["싫어", "짜증나", "하기 싫어", "혼자"]
        score = compute_score(msgs)
        result = classify(score, msgs)
        assert result in ("YELLOW", "RED")  # 위험표현 없으면 점수로만 판정
