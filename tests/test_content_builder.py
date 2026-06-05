"""
content_builder 순수 함수 유닛 테스트.

_parse_llm_json: LLM 출력 파싱 (펜스 제거, 엣지케이스)
_coerce_step4_choice: step4 choice 타입 방어 보정
"""
import pytest
from app.services.content_builder import _parse_llm_json, _coerce_step4_choice


class TestParseLlmJson:
    def test_순수_json(self):
        assert _parse_llm_json('{"key": "value"}') == {"key": "value"}

    def test_json_펜스_with_언어태그(self):
        raw = '```json\n{"key": "value"}\n```'
        assert _parse_llm_json(raw) == {"key": "value"}

    def test_json_펜스_without_언어태그(self):
        raw = '```\n{"key": "value"}\n```'
        assert _parse_llm_json(raw) == {"key": "value"}

    def test_앞뒤_공백(self):
        assert _parse_llm_json('  {"key": "value"}  ') == {"key": "value"}

    def test_중첩_json(self):
        raw = '{"a": {"b": [1, 2, 3]}}'
        assert _parse_llm_json(raw) == {"a": {"b": [1, 2, 3]}}

    def test_깨진_json_예외(self):
        with pytest.raises(Exception):
            _parse_llm_json("이건 JSON이 아닙니다")

    def test_빈_문자열_예외(self):
        with pytest.raises(Exception):
            _parse_llm_json("")

    def test_펜스만_있고_내용_없음_예외(self):
        with pytest.raises(Exception):
            _parse_llm_json("```json\n```")


class TestCoerceStep4Choice:
    def test_정답은_항상_empathetic으로_강제(self):
        result = _coerce_step4_choice({"is_correct": True, "type": "pressuring"})
        assert result["type"] == "empathetic"

    def test_정답_이미_empathetic_이면_유지(self):
        result = _coerce_step4_choice({"is_correct": True, "type": "empathetic"})
        assert result["type"] == "empathetic"

    def test_허용된_오답_empathetic_그대로(self):
        result = _coerce_step4_choice({"is_correct": False, "type": "empathetic"})
        assert result["type"] == "empathetic"

    def test_허용된_오답_indifferent_그대로(self):
        result = _coerce_step4_choice({"is_correct": False, "type": "indifferent"})
        assert result["type"] == "indifferent"

    def test_허용된_오답_irrelevant_그대로(self):
        result = _coerce_step4_choice({"is_correct": False, "type": "irrelevant"})
        assert result["type"] == "irrelevant"

    def test_허용_외_오답은_indifferent로_보정(self):
        result = _coerce_step4_choice({"is_correct": False, "type": "pressuring"})
        assert result["type"] == "indifferent"

    def test_원본_딕셔너리_변경_없음(self):
        original = {"is_correct": True, "type": "wrong"}
        _coerce_step4_choice(original)
        assert original["type"] == "wrong"  # 원본 불변
