"""Tests for user-chosen charge card names."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.fifty_five.config_flow import FiftyFiveOptionsFlow
from custom_components.fifty_five.const import CONF_CARD_LABELS, charge_card_label
from custom_components.fifty_five.select import FiftyFiveChargeCardSelect
from custom_components.fifty_five.sensor import (
    SENSOR_DESCRIPTIONS,
    FiftyFiveChargeCardEnergySensor,
)

CARD_A = "NL-50F-C12345678-9"
CARD_B = "04A1B2C3D4E5F6"
CARDS = [
    {"id": "internal-a", "externalId": CARD_A, "cardProvider": {"name": "50Five"}},
    {"id": "internal-b", "externalId": CARD_B, "cardProvider": {"name": "District"}},
]
LABELS = {"internal-b": "Tesla"}
DATA = {
    "charge_cards": CARDS,
    "card_labels": LABELS,
    "charging_history": [{"totalEnergy": 10, "cardSnapshot": {"externalId": CARD_B}}],
    "charge_station_id": "station",
}


def _coordinator(data=DATA):
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = True
    coordinator.selected_card_id = None
    return coordinator


def _entry(options=None):
    entry = MagicMock()
    entry.entry_id = "entry"
    entry.options = options or {}
    return entry


class LabelFormattingTest(unittest.TestCase):
    def test_label_replaces_default_name(self) -> None:
        self.assertEqual(charge_card_label(CARDS[1], 2, LABELS), "Tesla (District, ••••E5F6)")
        self.assertEqual(charge_card_label(CARDS[0], 1, LABELS), "Card 1 (50Five, ••••78-9)")
        self.assertEqual(charge_card_label(CARDS[0], 1), "Card 1 (50Five, ••••78-9)")

    def test_last_transaction_card_uses_label(self) -> None:
        description = next(d for d in SENSOR_DESCRIPTIONS if d.key == "last_transaction_card")
        self.assertEqual(description.value_fn(DATA), "Tesla (District, ••••E5F6)")

    def test_card_energy_sensor_name_and_attributes(self) -> None:
        sensor = FiftyFiveChargeCardEnergySensor(_coordinator(), _entry(), CARDS[1], 2)
        self.assertEqual(sensor.name, "Tesla (District, ••••E5F6) Energy (30 days)")
        self.assertEqual(sensor.extra_state_attributes["label"], "Tesla")
        # Unique id is unaffected by renaming.
        self.assertEqual(sensor.unique_id, "entry_card_internal-b_energy_30d")

    def test_select_uses_labels_and_keeps_options_unique(self) -> None:
        data = {**DATA, "card_labels": {"internal-a": "Car", "internal-b": "Car"}}
        cards = [dict(CARDS[0]), {**CARDS[0], "id": "internal-c"}]  # same last four
        data["charge_cards"] = cards
        select = FiftyFiveChargeCardSelect(_coordinator(data), _entry())
        options = select.options[1:]
        self.assertEqual(len(set(options)), 2)
        self.assertEqual(options[0], "Car (50Five, ••••78-9)")


class OptionsFlowTest(unittest.IsolatedAsyncioTestCase):
    def _flow(self, options=None, cards=CARDS):
        entry = _entry(options)
        hass = MagicMock()
        hass.data = {"fifty_five": {"entry": SimpleNamespace(data={"charge_cards": cards})}}
        hass.config_entries.async_get_known_entry.return_value = entry
        flow = FiftyFiveOptionsFlow()
        flow.hass = hass
        flow.handler = "entry"
        return flow

    async def test_form_shows_masked_fields_with_current_labels(self) -> None:
        flow = self._flow({CONF_CARD_LABELS: {"internal-a": "Kia"}})
        result = await flow.async_step_init()
        self.assertEqual(result["type"], "form")
        keys = {str(k): k for k in result["data_schema"].schema}
        self.assertEqual(set(keys), {"Card 1 (50Five, ••••78-9)", "Card 2 (District, ••••E5F6)"})
        self.assertEqual(keys["Card 1 (50Five, ••••78-9)"].description["suggested_value"], "Kia")
        text = json.dumps([str(k) for k in keys], ensure_ascii=False)
        self.assertNotIn(CARD_A, text)
        self.assertNotIn(CARD_B, text)

    async def test_saves_labels_by_internal_id_and_keeps_other_options(self) -> None:
        flow = self._flow({"default_card_id": CARD_B, CONF_CARD_LABELS: {"old-card": "Old"}})
        result = await flow.async_step_init(
            {"Card 1 (50Five, ••••78-9)": "  Kia  ", "Card 2 (District, ••••E5F6)": ""}
        )
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(
            result["data"],
            {"default_card_id": CARD_B, CONF_CARD_LABELS: {"old-card": "Old", "internal-a": "Kia"}},
        )
        self.assertNotIn(CARD_A, json.dumps(result["data"][CONF_CARD_LABELS]))

    async def test_rejects_too_long_label(self) -> None:
        result = await self._flow().async_step_init({"Card 1 (50Five, ••••78-9)": "x" * 41})
        self.assertEqual(result["errors"], {"base": "label_too_long"})

    async def test_aborts_without_cards(self) -> None:
        result = await self._flow(cards=[]).async_step_init()
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "no_charge_cards")


if __name__ == "__main__":
    unittest.main()
