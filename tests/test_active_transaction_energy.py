"""Tests for active transaction energy sensor values."""

import unittest

from custom_components.fifty_five.sensor import _get_active_transaction_energy


class ActiveTransactionEnergyTest(unittest.TestCase):
    def test_converts_energy_delivered_from_wh_to_kwh(self) -> None:
        value = _get_active_transaction_energy(
            {"active_transaction": {"energyDelivered": 10660}}
        )

        self.assertEqual(value, 10.66)


if __name__ == "__main__":
    unittest.main()
