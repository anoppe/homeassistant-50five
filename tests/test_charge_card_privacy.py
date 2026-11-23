"""Tests ensuring charge card numbers are not exposed in state, attributes or logs."""

import json
import unittest
from unittest.mock import MagicMock

from custom_components.fifty_five.api import (
    _sanitize_payload_for_logging,
    _sanitize_response_for_logging,
)
from custom_components.fifty_five.const import mask_card_number
from custom_components.fifty_five.select import NONE_OPTION, FiftyFiveChargeCardSelect
from custom_components.fifty_five.sensor import SENSOR_DESCRIPTIONS

CARD_A = "NL-50F-C12345678-9"
CARD_B = "04A1B2C3D4E5F6"
CARDS = [
    {"id": "internal-a", "externalId": CARD_A, "cardProvider": {"name": "50Five"},
     "type": "RFID", "state": "active", "roaming": True},
    {"id": "internal-b", "externalId": CARD_B, "cardProvider": {"name": "50Five"},
     "type": "RFID", "state": "active", "roaming": False},
]


def _make_select(selected: str | None = None) -> FiftyFiveChargeCardSelect:
    coordinator = MagicMock()
    coordinator.data = {"charge_cards": CARDS, "charge_station_id": "station"}
    coordinator.selected_card_id = selected
    entry = MagicMock()
    entry.entry_id = "entry"
    entry.options = {}
    entity = FiftyFiveChargeCardSelect(coordinator, entry)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    return entity


def _assert_no_card_numbers(test: unittest.TestCase, value) -> None:
    text = json.dumps(value, default=str)
    for number in (CARD_A, CARD_B):
        test.assertNotIn(number, text)


class MaskCardNumberTest(unittest.TestCase):
    def test_masks_all_but_last_four(self) -> None:
        self.assertEqual(mask_card_number(CARD_A), "••••78-9")

    def test_short_or_missing_numbers_are_fully_masked(self) -> None:
        self.assertEqual(mask_card_number("1234"), "••••")
        self.assertEqual(mask_card_number(None), "••••")


class ChargeCardSelectTest(unittest.IsolatedAsyncioTestCase):
    def test_options_do_not_expose_card_numbers(self) -> None:
        options = _make_select().options
        self.assertEqual(options[0], NONE_OPTION)
        self.assertEqual(len(set(options)), 3)
        _assert_no_card_numbers(self, options)

    def test_current_option_and_attributes_do_not_expose_card_numbers(self) -> None:
        entity = _make_select(selected=CARD_B)
        self.assertEqual(entity.current_option, entity.options[2])
        _assert_no_card_numbers(self, entity.current_option)
        attributes = entity.extra_state_attributes
        _assert_no_card_numbers(self, attributes)
        self.assertNotIn("external_id", attributes)
        self.assertNotIn("card_id", attributes)
        self.assertEqual(attributes["provider"], "50Five")

    def test_legacy_internal_id_selection_still_resolves(self) -> None:
        entity = _make_select(selected="internal-a")
        self.assertEqual(entity.current_option, entity.options[1])

    async def test_selecting_option_stores_external_id_internally(self) -> None:
        entity = _make_select()
        await entity.async_select_option(entity.options[2])
        entity.coordinator.set_selected_card.assert_called_once_with(CARD_B)
        options = entity.hass.config_entries.async_update_entry.call_args.kwargs["options"]
        self.assertEqual(options["default_card_id"], CARD_B)

    async def test_selection_logging_does_not_expose_card_numbers(self) -> None:
        entity = _make_select()
        with self.assertLogs("custom_components.fifty_five.select", level="DEBUG") as logs:
            entity.options
            await entity.async_select_option(entity.options[1])
        _assert_no_card_numbers(self, logs.output)


class ChargeCardSensorTest(unittest.TestCase):
    def test_no_sensor_exposes_card_numbers(self) -> None:
        data = {"charge_cards": CARDS * 10}
        keys = {description.key for description in SENSOR_DESCRIPTIONS}
        self.assertNotIn("charge_cards_summary", keys)
        for description in SENSOR_DESCRIPTIONS:
            try:
                value = description.value_fn(data)
            except Exception:  # unrelated sensors may need other data
                continue
            _assert_no_card_numbers(self, value)

    def test_card_count_sensor_remains(self) -> None:
        count = next(d for d in SENSOR_DESCRIPTIONS if d.key == "charge_card_count")
        self.assertEqual(count.value_fn({"charge_cards": CARDS}), 2)


class RemovedSummarySensorTest(unittest.IsolatedAsyncioTestCase):
    async def test_setup_removes_stale_summary_entity(self) -> None:
        from unittest.mock import patch

        from custom_components.fifty_five import sensor

        registry = MagicMock()
        registry.async_get_entity_id.return_value = "sensor.charge_cards_details"
        coordinator = MagicMock()
        coordinator.data = {"charge_station_id": "station"}
        hass = MagicMock()
        hass.data = {"fifty_five": {"entry": coordinator}}
        entry = MagicMock()
        entry.entry_id = "entry"
        with patch.object(sensor.er, "async_get", return_value=registry):
            await sensor.async_setup_entry(hass, entry, MagicMock())
        registry.async_get_entity_id.assert_called_once_with(
            "sensor", "fifty_five", "entry_charge_cards_summary"
        )
        registry.async_remove.assert_called_once_with("sensor.charge_cards_details")


class LogSanitizationTest(unittest.TestCase):
    def test_start_transaction_payload_masks_card(self) -> None:
        payload = {"query": "q", "variables": {"chargeStationId": "s", "card": CARD_A}}
        _assert_no_card_numbers(self, _sanitize_payload_for_logging(payload))
        self.assertEqual(payload["variables"]["card"], CARD_A)

    def test_response_masks_nested_external_ids(self) -> None:
        response = {"data": {"getCustomerById": {"cards": CARDS},
                             "getTransactions": {"items": [{"card": {"externalId": CARD_B}}]}}}
        _assert_no_card_numbers(self, _sanitize_response_for_logging(response))
        self.assertEqual(response["data"]["getCustomerById"]["cards"][0]["externalId"], CARD_A)


class EchoedCardRedactionTest(unittest.IsolatedAsyncioTestCase):
    async def _client_returning(self, status: int, body: str):
        from unittest.mock import AsyncMock

        import aiohttp

        from custom_components.fifty_five.api import FiftyFiveApiClient

        response = MagicMock()
        response.status = status
        response.text = AsyncMock(return_value=body)
        if status >= 400:
            response.raise_for_status.side_effect = aiohttp.ClientResponseError(
                MagicMock(), (), status=status
            )
        session = MagicMock()
        session.post.return_value.__aenter__ = AsyncMock(return_value=response)
        client = FiftyFiveApiClient(session, "user@example.com", "pw", "station", "channel")
        client._access_token = "token"
        return client

    async def test_graphql_error_echoing_card_is_redacted(self) -> None:
        client = await self._client_returning(
            200, json.dumps({"errors": [{"message": f"Card {CARD_A} is blocked"}]})
        )
        with self.assertLogs("custom_components.fifty_five.api", level="DEBUG") as logs:
            self.assertFalse(await client.start_transaction(CARD_A))
        _assert_no_card_numbers(self, logs.output)

    async def test_raw_body_echoing_card_is_redacted(self) -> None:
        from custom_components.fifty_five.api import FiftyFiveApiError

        client = await self._client_returning(200, f"<html>bad card {CARD_A}</html>")
        with self.assertLogs("custom_components.fifty_five.api", level="DEBUG") as logs:
            with self.assertRaises(FiftyFiveApiError) as raised:
                await client._execute_query("q", {"card": CARD_A})
        _assert_no_card_numbers(self, logs.output)
        _assert_no_card_numbers(self, str(raised.exception))


class CoordinatorLoggingTest(unittest.TestCase):
    def test_set_selected_card_does_not_log_card_number(self) -> None:
        from custom_components.fifty_five.coordinator import FiftyFiveDataUpdateCoordinator

        coordinator = FiftyFiveDataUpdateCoordinator.__new__(FiftyFiveDataUpdateCoordinator)
        with self.assertLogs("custom_components.fifty_five.coordinator", level="DEBUG") as logs:
            coordinator.set_selected_card(CARD_A)
        _assert_no_card_numbers(self, logs.output)
        self.assertEqual(coordinator.selected_card_id, CARD_A)


if __name__ == "__main__":
    unittest.main()
