"""
content_builder 순수 함수 유닛 테스트.

_coerce_step4_choice: step4 choice 타입 방어 보정
(LLM 출력 파싱 테스트는 tests/test_llm_json.py 로 이동)
"""
from app.services.content_builder import _coerce_step4_choice


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
