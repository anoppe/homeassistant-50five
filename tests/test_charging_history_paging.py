"""Tests for following all pages of the 30-day charging history."""

import unittest
from unittest.mock import AsyncMock, MagicMock

from custom_components.fifty_five import api
from custom_components.fifty_five.api import FiftyFiveApiClient


def _page(ids, has_next):
    return {"getTransactions": {"hasNext": has_next, "items": [{"id": i} for i in ids]}}


def _client(responses):
    client = FiftyFiveApiClient(MagicMock(), "user@example.com", "pw", "station", "channel")
    client._execute_query = AsyncMock(side_effect=responses)
    return client


def _pages_requested(client):
    return [
        c.kwargs["variables"]["getTransactionsFilters"]["page"]
        for c in client._execute_query.call_args_list
    ]


class ChargingHistoryPagingTest(unittest.IsolatedAsyncioTestCase):
    async def test_follows_has_next_across_pages(self) -> None:
        client = _client([_page([1, 2], True), _page([3, 4], True), _page([5], False)])
        items = await client.get_charging_history(items_per_page=2)
        self.assertEqual([i["id"] for i in items], [1, 2, 3, 4, 5])
        self.assertEqual(_pages_requested(client), [1, 2, 3])

    async def test_single_page(self) -> None:
        client = _client([_page([1], False)])
        self.assertEqual(len(await client.get_charging_history()), 1)
        self.assertEqual(_pages_requested(client), [1])

    async def test_empty_or_missing_result(self) -> None:
        self.assertEqual(await _client([{"getTransactions": None}]).get_charging_history(), [])

    async def test_stops_when_backend_repeats_same_page(self) -> None:
        client = _client([_page([1, 2], True), _page([1, 2], True)])
        items = await client.get_charging_history(items_per_page=2)
        self.assertEqual([i["id"] for i in items], [1, 2])
        self.assertEqual(_pages_requested(client), [1, 2])

    async def test_page_cap(self) -> None:
        cap = api.HISTORY_MAX_PAGES
        client = _client([_page([n], True) for n in range(cap + 5)])
        with self.assertLogs(api._LOGGER, "WARNING"):
            items = await client.get_charging_history(items_per_page=1)
        self.assertEqual(len(items), cap)


if __name__ == "__main__":
    unittest.main()
