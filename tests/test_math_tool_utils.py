"""
math_tool 순수 함수 유닛 테스트.

_is_known_concept: concept 검증 (sentinel, 목록 매칭)
_build_math_cta: lessonStatus → CTA 조립 분기
"""
import pytest
from app.agents.leo.tools.math_tool import _is_known_concept, _build_math_cta
from app.schemas.chat import StepCTA

CONCEPTS = [
    {"concept": "받아올림 없는 세 자리 수 덧셈과 뺄셈", "stepTitle": "1단계"},
    {"concept": "분수의 덧셈과 뺄셈", "stepTitle": "2단계"},
    {"concept": "소수의 곱셈", "stepTitle": "3단계"},
]


class TestIsKnownConcept:
    def test_정확_일치(self):
        assert _is_known_concept("분수의 덧셈과 뺄셈", CONCEPTS) is True

    def test_목록에_없는_개념(self):
        assert _is_known_concept("곱셈구구", CONCEPTS) is False

    def test_sentinel_모름은_항상_False(self):
        assert _is_known_concept("모름", CONCEPTS) is False

    def test_빈_목록(self):
        assert _is_known_concept("분수의 덧셈과 뺄셈", []) is False

    def test_부분_문자열은_불일치(self):
        # "분수"만으로는 "분수의 덧셈과 뺄셈"에 매칭되지 않아야 함
        assert _is_known_concept("분수", CONCEPTS) is False

    def test_공백_차이_불일치(self):
        assert _is_known_concept("분수의덧셈과뺄셈", CONCEPTS) is False

    def test_빈_문자열(self):
        assert _is_known_concept("", CONCEPTS) is False


class TestBuildMathCta:
    def test_AVAILABLE(self):
        cta = _build_math_cta({"lessonStatus": "AVAILABLE", "stepId": 3, "stepTitle": "3단계"})
        assert isinstance(cta, StepCTA)
        assert cta.step_id == 3
        assert cta.type == "navigate_to_step"

    def test_IN_PROGRESS(self):
        cta = _build_math_cta({"lessonStatus": "IN_PROGRESS", "stepId": 5, "stepTitle": "5단계"})
        assert isinstance(cta, StepCTA)
        assert cta.step_id == 5

    def test_COMPLETED(self):
        cta = _build_math_cta({"lessonStatus": "COMPLETED", "stepId": 2, "stepTitle": "2단계"})
        assert isinstance(cta, StepCTA)
        assert cta.step_id == 2

    def test_LOCKED_현재_가능한_step으로(self):
        cta = _build_math_cta({
            "lessonStatus": "LOCKED",
            "currentAvailableStepId": 1,
            "currentAvailableStepTitle": "1단계",
        })
        assert isinstance(cta, StepCTA)
        assert cta.step_id == 1

    def test_NOT_FOUND_는_None(self):
        assert _build_math_cta({"lessonStatus": "NOT_FOUND"}) is None

    def test_알_수_없는_status는_None(self):
        assert _build_math_cta({"lessonStatus": "UNKNOWN_XYZ"}) is None
