"""Tests for attributing charging sessions and energy to charge cards."""

import json
import unittest
from unittest.mock import MagicMock

from custom_components.fifty_five.sensor import (
    SENSOR_DESCRIPTIONS,
    FiftyFiveChargeCardEnergySensor,
)

CARD_A = "NL-50F-C12345678-9"
CARD_B = "04A1B2C3D4E5F6"
FOREIGN = "NL-XYZ-C99998888-1"
CARDS = [
    {"id": "internal-a", "externalId": CARD_A, "cardProvider": {"name": "50Five"}},
    {"id": "internal-b", "externalId": CARD_B, "cardProvider": {"name": "District"}},
]
HISTORY = [
    {"startDate": "2026-11-09T18:00:00Z", "totalEnergy": 12.5, "cardSnapshot": {"externalId": CARD_B}},
    {"startDate": "2026-11-08T18:00:00Z", "totalEnergy": 20.0, "cardSnapshot": {"externalId": CARD_A}},
    {"startDate": "2026-11-07T18:00:00Z", "totalEnergy": "7,25", "cardSnapshot": {"externalId": CARD_B}},
    {"startDate": "2026-11-06T18:00:00Z", "totalEnergy": 3.0, "cardSnapshot": None},
]
DATA = {"charge_cards": CARDS, "charging_history": HISTORY, "charge_station_id": "station"}
SECRETS = (CARD_A, CARD_B, FOREIGN)


def _value(key, data=DATA):
    description = next(d for d in SENSOR_DESCRIPTIONS if d.key == key)
    return description.value_fn(data)


def _card_sensor(card, index):
    coordinator = MagicMock()
    coordinator.data = DATA
    coordinator.last_update_success = True
    entry = MagicMock()
    entry.entry_id = "entry"
    return FiftyFiveChargeCardEnergySensor(coordinator, entry, card, index)


class LastTransactionCardTest(unittest.TestCase):
    def test_last_transaction_card_is_masked_label(self) -> None:
        self.assertEqual(_value("last_transaction_card"), "Card 2 (District, ••••E5F6)")

    def test_unknown_card_is_masked(self) -> None:
        data = {**DATA, "charging_history": [{"cardSnapshot": {"externalId": FOREIGN}}]}
        self.assertEqual(_value("last_transaction_card", data), "Other card (••••88-1)")

    def test_missing_snapshot_or_history(self) -> None:
        self.assertIsNone(_value("last_transaction_card", {**DATA, "charging_history": [{}]}))
        self.assertIsNone(_value("last_transaction_card", {**DATA, "charging_history": []}))


class ChargeCardEnergySensorTest(unittest.TestCase):
    def test_energy_is_split_per_card(self) -> None:
        self.assertEqual(_card_sensor(CARDS[0], 1).native_value, 20.0)
        self.assertEqual(_card_sensor(CARDS[1], 2).native_value, 19.75)

    def test_attributes(self) -> None:
        attrs = _card_sensor(CARDS[1], 2).extra_state_attributes
        self.assertEqual(attrs["transactions"], 2)
        self.assertEqual(attrs["last_transaction_date"], "2026-11-09T18:00:00Z")
        self.assertEqual(attrs["last_transaction_energy"], 12.5)
        self.assertEqual(attrs["card_number"], "••••E5F6")

    def test_no_card_numbers_exposed(self) -> None:
        for index, card in enumerate(CARDS, start=1):
            sensor = _card_sensor(card, index)
            text = json.dumps(
                [sensor.unique_id, sensor.name, sensor.native_value, sensor.extra_state_attributes],
                default=str,
            )
            for secret in SECRETS:
                self.assertNotIn(secret, text)
        self.assertEqual(_card_sensor(CARDS[0], 1).unique_id, "entry_card_internal-a_energy_30d")

    def test_removed_card_is_unavailable(self) -> None:
        sensor = _card_sensor({"id": "gone", "externalId": "x" * 10}, 3)
        self.assertFalse(sensor.available)
        self.assertIsNone(sensor.native_value)


if __name__ == "__main__":
    unittest.main()
