import pytest
from app.core.config import settings

# 통합 테스트 마커 등록
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: 실제 Gemini API를 호출하는 통합 테스트 (GOOGLE_API_KEY 필요)"
    )

# 통합 테스트는 --integration 플래그 없으면 자동 skip
def pytest_collection_modifyitems(config, items):
    if config.getoption("--integration", default=False):
        return
    skip = pytest.mark.skip(reason="--integration 플래그 없음. 실행하려면: pytest --integration")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)

def pytest_addoption(parser):
    parser.addoption("--integration", action="store_true", default=False, help="통합 테스트 포함 실행")
