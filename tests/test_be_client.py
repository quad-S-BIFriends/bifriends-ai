"""BEClient 내부 API 파라미터 검증."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.be_client import BEClient


def test_chat_messages_range_params_matches_be_contract():
    params = BEClient._chat_messages_range_params(5, "2026-06-22", "2026-06-28")

    assert params == {
        "memberId": 5,
        "from": "2026-06-22T00:00:00",
        "to": "2026-06-28T23:59:59",
    }


@pytest.mark.asyncio
async def test_get_weekly_messages_sends_be_contract_params():
    client = BEClient()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"messages": []}

    mock_http = AsyncMock()
    mock_http.get.return_value = mock_response
    client._client = mock_http

    await client.get_weekly_messages(5, "2026-06-22", "2026-06-28")

    mock_http.get.assert_called_once_with(
        "/api/v1/chat/messages",
        params={
            "memberId": 5,
            "from": "2026-06-22T00:00:00",
            "to": "2026-06-28T23:59:59",
        },
    )
