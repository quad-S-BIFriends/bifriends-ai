"""
app.core.llm_json 유닛 테스트.

parse_llm_json: LLM 출력에서 코드펜스 제거 후 JSON 파싱 (엣지케이스 포함).
LLM이 ```json ... ``` 으로 감싸 보내는 흔한 케이스를 방어하는지 확인한다.
"""
import pytest

from app.core.llm_json import parse_llm_json, strip_code_fence


class TestParseLlmJson:
    def test_순수_json(self):
        assert parse_llm_json('{"key": "value"}') == {"key": "value"}

    def test_json_펜스_with_언어태그(self):
        raw = '```json\n{"key": "value"}\n```'
        assert parse_llm_json(raw) == {"key": "value"}

    def test_json_펜스_without_언어태그(self):
        raw = '```\n{"key": "value"}\n```'
        assert parse_llm_json(raw) == {"key": "value"}

    def test_펜스_뒤_개행공백_붙어도_제거(self):
        raw = '```json\n{"key": "value"}\n```  \n'
        assert parse_llm_json(raw) == {"key": "value"}

    def test_앞뒤_공백(self):
        assert parse_llm_json('  {"key": "value"}  ') == {"key": "value"}

    def test_중첩_json(self):
        raw = '{"a": {"b": [1, 2, 3]}}'
        assert parse_llm_json(raw) == {"a": {"b": [1, 2, 3]}}

    def test_깨진_json_예외(self):
        with pytest.raises(Exception):
            parse_llm_json("이건 JSON이 아닙니다")

    def test_빈_문자열_예외(self):
        with pytest.raises(Exception):
            parse_llm_json("")

    def test_펜스만_있고_내용_없음_예외(self):
        with pytest.raises(Exception):
            parse_llm_json("```json\n```")


class TestStripCodeFence:
    def test_펜스_없으면_그대로(self):
        assert strip_code_fence("hello") == "hello"

    def test_언어태그_펜스_제거(self):
        assert strip_code_fence("```json\n{}\n```") == "{}"

    def test_플레인_펜스_제거(self):
        assert strip_code_fence("```\ntext\n```") == "text"
