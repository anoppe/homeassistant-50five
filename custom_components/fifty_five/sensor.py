"""Sensor platform for 50Five EV Charger."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, charge_card_label, mask_card_number, normalize_global_status
from .coordinator import FiftyFiveDataUpdateCoordinator


def _coerce_number(value: Any) -> float | int | None:
    """Convert API values to a numeric type when possible."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        normalized = value.strip().replace(",", ".")
        if not normalized:
            return None
        try:
            number = float(normalized)
        except ValueError:
            return None
        return int(number) if number.is_integer() else number
    return None


def _parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO datetime value from the API."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _get_transaction_costs(transaction: dict[str, Any]) -> list[float]:
    """Extract numeric transaction costs."""
    costs: list[float] = []
    for price in transaction.get("transactionPrices", []):
        cost = _coerce_number(price.get("totalCost"))
        if cost is not None:
            costs.append(float(cost))
    return costs


def _get_latest_transaction(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the latest transaction from charging history."""
    history = data.get("charging_history", [])
    if not history:
        return None
    return history[0]


def _get_active_transaction_data(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return active transaction data when present."""
    active_transaction = data.get("active_transaction")
    return active_transaction if isinstance(active_transaction, dict) else None


def _normalize_duration_minutes(duration: Any, *, energy_kwh: Any = None) -> int | None:
    """Normalize API duration values to minutes.

    The 50Five API has returned duration values in different units depending on
    the endpoint/account: minutes, seconds, milliseconds, and occasionally hour-like
    values for completed sessions. This helper converts them to minutes using a small
    heuristic that prefers the least surprising value.
    """
    numeric_duration = _coerce_number(duration)
    if numeric_duration is None:
        return None

    value = float(numeric_duration)
    if value < 0:
        return None
    if value == 0:
        return 0

    if value >= 86_400:
        return round(value / 60_000)

    if value > 1_440:
        return round(value / 60)

    energy_value = _coerce_number(energy_kwh)
    if energy_value is not None and 0 < value <= 24:
        minimum_plausible_minutes = (float(energy_value) / 22.0) * 60
        if minimum_plausible_minutes > 0 and value < (minimum_plausible_minutes * 0.75):
            return round(value * 60)

    return round(value)


def _get_active_transaction_energy(data: dict[str, Any]) -> float | int | None:
    """Get the delivered energy for the active transaction."""
    active_transaction = _get_active_transaction_data(data)
    if not active_transaction:
        return None
    energy_wh = _coerce_number(active_transaction.get("energyDelivered"))
    if energy_wh is None:
        return None
    return round(float(energy_wh) / 1000, 3)


def _get_active_transaction_duration(data: dict[str, Any]) -> int | None:
    """Get the active transaction duration in minutes."""
    active_transaction = _get_active_transaction_data(data)
    if not active_transaction:
        return None

    duration = _normalize_duration_minutes(
        active_transaction.get("durationCharging"),
        energy_kwh=active_transaction.get("energyDelivered"),
    )
    if duration is not None:
        return duration

    start_date = _parse_datetime(active_transaction.get("startDate"))
    if start_date is None:
        return None

    return max(round((datetime.now(timezone.utc) - start_date).total_seconds() / 60), 0)


def _get_active_transaction_amount(data: dict[str, Any]) -> float | int | None:
    """Get the running amount for the active transaction."""
    active_transaction = _get_active_transaction_data(data)
    if not active_transaction:
        return None
    return _coerce_number(active_transaction.get("totalAmount"))


def _get_active_transaction_address(data: dict[str, Any]) -> str | None:
    """Get the address for the active transaction."""
    active_transaction = _get_active_transaction_data(data)
    if not active_transaction:
        return None
    return active_transaction.get("address")


def _get_history_total_energy(data: dict[str, Any]) -> float | None:
    """Calculate total energy from charging history."""
    history = data.get("charging_history", [])
    if not history:
        return None
    total = sum(item.get("totalEnergy", 0) or 0 for item in history)
    return round(total, 2)


def _get_history_total_cost(data: dict[str, Any]) -> float | None:
    """Calculate total cost from charging history."""
    history = data.get("charging_history", [])
    if not history:
        return None
    total = 0.0
    for item in history:
        for cost in _get_transaction_costs(item):
            if cost:
                total += abs(cost)
    return round(total, 2)


def _get_history_total_reimbursement(data: dict[str, Any]) -> float | None:
    """Calculate total HCC reimbursement from charging history."""
    history = data.get("charging_history", [])
    if not history:
        return None
    total = 0.0
    for item in history:
        for cost in _get_transaction_costs(item):
            # Sum negative costs (HCC reimbursements) as positive value
            if cost and cost < 0:
                total += abs(cost)
    return round(total, 2) if total > 0 else None


def _get_history_transaction_count(data: dict[str, Any]) -> int | None:
    """Get the number of transactions in history."""
    history = data.get("charging_history", [])
    return len(history) if history is not None else None


def _get_last_transaction_date(data: dict[str, Any]) -> str | None:
    """Get the date of the last transaction."""
    last = _get_latest_transaction(data)
    if not last:
        return None
    start_date = last.get("startDate")
    if start_date:
        try:
            dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            return start_date
    return None


def _get_last_transaction_energy(data: dict[str, Any]) -> float | None:
    """Get the energy of the last transaction."""
    last = _get_latest_transaction(data)
    if not last:
        return None
    energy = _coerce_number(last.get("totalEnergy"))
    return float(energy) if isinstance(energy, int | float) else None


def _get_last_transaction_duration(data: dict[str, Any]) -> int | None:
    """Get the duration of the last transaction in minutes."""
    last = _get_latest_transaction(data)
    if not last:
        return None
    return _normalize_duration_minutes(
        last.get("totalDuration"),
        energy_kwh=last.get("totalEnergy"),
    )


def _get_last_transaction_cost(data: dict[str, Any]) -> float | None:
    """Get the cost of the last transaction.

    The API can return a negative net cost for HCC/reimbursement transactions.
    Display the absolute value as a positive charge amount for Home Assistant.
    """
    last = _get_latest_transaction(data)
    if not last:
        return None
    costs = _get_transaction_costs(last)
    if not costs:
        return None

    total_cost = round(sum(costs), 2)
    if total_cost < 0:
        return abs(total_cost)
    return total_cost if total_cost > 0 else 0.0


def _get_history_currency(data: dict[str, Any]) -> str | None:
    """Get the currency from charging history."""
    history = data.get("charging_history", [])
    if not history:
        return None
    prices = history[0].get("transactionPrices", [])
    for price in prices:
        currency = price.get("currency", {})
        if currency and currency.get("code"):
            return currency["code"]
    return None


def _get_transaction_card_number(transaction: dict[str, Any]) -> str | None:
    """Return the card number that authorized a history transaction (internal use only)."""
    snapshot = transaction.get("cardSnapshot") or {}
    return snapshot.get("externalId") or None


def _find_charge_card(
    data: dict[str, Any], card_number: str
) -> tuple[int, dict[str, Any]] | None:
    """Return the (1-based index, card) for a card number from the account's cards."""
    for index, card in enumerate(data.get("charge_cards", []) or [], start=1):
        if card.get("externalId") == card_number:
            return index, card
    return None


def _describe_card_number(data: dict[str, Any], card_number: str | None) -> str | None:
    """Return a masked, human-readable label for the card that authorized a session."""
    if not card_number:
        return None
    match = _find_charge_card(data, card_number)
    if match:
        index, card = match
        return charge_card_label(card, index, data.get("card_labels"))
    # Card not on this account (e.g. a guest or district card of another customer).
    return f"Other card ({mask_card_number(card_number)})"


def _get_last_transaction_card(data: dict[str, Any]) -> str | None:
    """Get the masked label of the card that authorized the last transaction."""
    last = _get_latest_transaction(data)
    if not last:
        return None
    return _describe_card_number(data, _get_transaction_card_number(last))


def _get_card_history_transactions(
    data: dict[str, Any], card_number: str | None
) -> list[dict[str, Any]]:
    """Return the 30-day history transactions authorized by the given card."""
    if not card_number:
        return []
    return [
        item
        for item in data.get("charging_history", []) or []
        if _get_transaction_card_number(item) == card_number
    ]


def _get_charge_card_count(data: dict[str, Any]) -> int:
    """Get the number of charge cards."""
    cards = data.get("charge_cards", [])
    return len(cards)


@dataclass(frozen=True)
class FiftyFiveSensorEntityDescriptionMixin:
    """Mixin for required keys."""

    value_fn: Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class FiftyFiveSensorEntityDescription(
    SensorEntityDescription, FiftyFiveSensorEntityDescriptionMixin
):
    """Describes a 50Five sensor entity."""


SENSOR_DESCRIPTIONS: tuple[FiftyFiveSensorEntityDescription, ...] = (
    FiftyFiveSensorEntityDescription(
        key="channel_status",
        name="Channel Status",
        icon="mdi:ev-station",
        value_fn=lambda data: normalize_global_status(
            data.get("channel", {}).get("globalStatus")
        ),
    ),
    FiftyFiveSensorEntityDescription(
        key="authorization_mode",
        name="Authorization Mode",
        icon="mdi:shield-key",
        value_fn=lambda data: data.get("overview", {}).get("accessOptions", {}).get("authorizationMode"),
    ),
    FiftyFiveSensorEntityDescription(
        key="access_type",
        name="Access Type",
        icon="mdi:lock-open",
        value_fn=lambda data: data.get("overview", {}).get("accessOptions", {}).get("accessType"),
    ),
    FiftyFiveSensorEntityDescription(
        key="published_on_map",
        name="Published on Map",
        icon="mdi:map-marker",
        value_fn=lambda data: data.get("overview", {}).get("accessOptions", {}).get("publishedOnMap"),
    ),
    FiftyFiveSensorEntityDescription(
        key="hcc_enabled",
        name="Home Charging Compensation",
        icon="mdi:cash",
        value_fn=lambda data: "Enabled" if data.get("overview", {}).get("homeChargingCompensation", {}).get("hccEnabled") else "Disabled",
    ),
    FiftyFiveSensorEntityDescription(
        key="hcc_tariff",
        name="HCC Tariff (excl. VAT)",
        icon="mdi:currency-eur",
        value_fn=lambda data: data.get("overview", {}).get("homeChargingCompensation", {}).get("hccTariff"),
    ),
    FiftyFiveSensorEntityDescription(
        key="hcc_tariff_incl_vat",
        name="HCC Tariff (incl. VAT)",
        icon="mdi:currency-eur",
        value_fn=lambda data: round(data.get("overview", {}).get("homeChargingCompensation", {}).get("hccTariff", 0) * 1.21, 4) if data.get("overview", {}).get("homeChargingCompensation", {}).get("hccTariff") else None,
    ),
    FiftyFiveSensorEntityDescription(
        key="active_transaction_energy",
        name="Active Transaction Energy",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_get_active_transaction_energy,
    ),
    FiftyFiveSensorEntityDescription(
        key="active_transaction_duration",
        name="Active Transaction Duration",
        icon="mdi:timer",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        value_fn=_get_active_transaction_duration,
    ),
    FiftyFiveSensorEntityDescription(
        key="active_transaction_amount",
        name="Active Transaction Amount",
        icon="mdi:cash",
        value_fn=_get_active_transaction_amount,
    ),
    FiftyFiveSensorEntityDescription(
        key="active_transaction_address",
        name="Active Transaction Address",
        icon="mdi:map-marker",
        value_fn=_get_active_transaction_address,
    ),
    # Charging History Sensors
    FiftyFiveSensorEntityDescription(
        key="history_transaction_count",
        name="Transactions (30 days)",
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL,
        value_fn=_get_history_transaction_count,
    ),
    FiftyFiveSensorEntityDescription(
        key="history_total_energy",
        name="Total Energy (30 days)",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=_get_history_total_energy,
    ),
    FiftyFiveSensorEntityDescription(
        key="history_total_cost",
        name="Total Cost (30 days)",
        icon="mdi:cash-multiple",
        state_class=SensorStateClass.TOTAL,
        value_fn=_get_history_total_cost,
    ),
    FiftyFiveSensorEntityDescription(
        key="history_total_reimbursement",
        name="HCC Reimbursement (30 days)",
        icon="mdi:cash-refund",
        state_class=SensorStateClass.TOTAL,
        value_fn=_get_history_total_reimbursement,
    ),
    FiftyFiveSensorEntityDescription(
        key="last_transaction_date",
        name="Last Transaction Date",
        icon="mdi:calendar",
        value_fn=_get_last_transaction_date,
    ),
    FiftyFiveSensorEntityDescription(
        key="last_transaction_energy",
        name="Last Transaction Energy",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        value_fn=_get_last_transaction_energy,
    ),
    FiftyFiveSensorEntityDescription(
        key="last_transaction_duration",
        name="Last Transaction Duration",
        icon="mdi:timer",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        value_fn=_get_last_transaction_duration,
    ),
    FiftyFiveSensorEntityDescription(
        key="last_transaction_card",
        name="Last Transaction Card",
        icon="mdi:credit-card-check",
        value_fn=_get_last_transaction_card,
    ),
    FiftyFiveSensorEntityDescription(
        key="last_transaction_cost",
        name="Last Transaction Cost",
        icon="mdi:cash",
        value_fn=_get_last_transaction_cost,
    ),
    # Charge Cards Sensors
    FiftyFiveSensorEntityDescription(
        key="charge_card_count",
        name="Charge Cards",
        icon="mdi:credit-card-multiple",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_get_charge_card_count,
    ),
)

# Removed because its state exposed charge card numbers.
REMOVED_SENSOR_KEYS = ("charge_cards_summary",)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up 50Five sensors based on a config entry."""
    coordinator: FiftyFiveDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entity_registry = er.async_get(hass)
    for key in REMOVED_SENSOR_KEYS:
        if entity_id := entity_registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{key}"
        ):
            entity_registry.async_remove(entity_id)

    async_add_entities(
        FiftyFiveSensor(coordinator, description, entry)
        for description in SENSOR_DESCRIPTIONS
    )

    # One energy sensor per charge card, so usage can be split per card (e.g. per car).
    known_card_keys: set[str] = set()

    @callback
    def _add_new_card_sensors() -> None:
        new_entities = []
        for index, card in enumerate(
            (coordinator.data or {}).get("charge_cards", []) or [], start=1
        ):
            card_key = _card_key(card)
            if not card_key or card_key in known_card_keys:
                continue
            known_card_keys.add(card_key)
            new_entities.append(
                FiftyFiveChargeCardEnergySensor(coordinator, entry, card, index)
            )
        if new_entities:
            async_add_entities(new_entities)

    _add_new_card_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_card_sensors))


def _card_key(card: dict[str, Any]) -> str | None:
    """Return a stable identifier for a card that is not the (secret) card number."""
    card_id = card.get("id")
    return str(card_id) if card_id else None


def _device_info(coordinator: FiftyFiveDataUpdateCoordinator, entry: ConfigEntry) -> DeviceInfo:
    """Return the shared device info for all 50Five sensors."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"50Five Charger {coordinator.data.get('charge_station_id', '')}",
        manufacturer="50Five",
        model="EV Charger",
    )


class FiftyFiveSensor(
    CoordinatorEntity[FiftyFiveDataUpdateCoordinator], SensorEntity
):
    """Representation of a 50Five sensor."""

    entity_description: FiftyFiveSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FiftyFiveDataUpdateCoordinator,
        description: FiftyFiveSensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.entity_description.value_fn(self.coordinator.data)
        return None


class FiftyFiveChargeCardEnergySensor(
    CoordinatorEntity[FiftyFiveDataUpdateCoordinator], SensorEntity
):
    """Energy charged with a single charge card over the last 30 days."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:credit-card-outline"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: FiftyFiveDataUpdateCoordinator,
        entry: ConfigEntry,
        card: dict[str, Any],
        index: int,
    ) -> None:
        """Initialize the per-card energy sensor."""
        super().__init__(coordinator)
        self._card_key = _card_key(card)
        # Unique ID uses the internal card id, never the card number.
        self._attr_unique_id = f"{entry.entry_id}_card_{self._card_key}_energy_30d"
        self._index = index
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def name(self) -> str:
        """Return the name, following the card's user-chosen label."""
        card = self._card()
        if card is None:
            return f"Card {self._index} Energy (30 days)"
        cards = (self.coordinator.data or {}).get("charge_cards", []) or []
        index = next(
            (i for i, c in enumerate(cards, start=1) if _card_key(c) == self._card_key),
            self._index,
        )
        labels = (self.coordinator.data or {}).get("card_labels")
        return f"{charge_card_label(card, index, labels)} Energy (30 days)"

    def _card(self) -> dict[str, Any] | None:
        for card in (self.coordinator.data or {}).get("charge_cards", []) or []:
            if _card_key(card) == self._card_key:
                return card
        return None

    def _transactions(self) -> list[dict[str, Any]]:
        card = self._card()
        if not card or not self.coordinator.data:
            return []
        return _get_card_history_transactions(self.coordinator.data, card.get("externalId"))

    @property
    def available(self) -> bool:
        """Return False when the card is no longer on the account."""
        return super().available and self._card() is not None

    @property
    def native_value(self) -> float | None:
        """Return the total energy charged with this card in the last 30 days."""
        if self._card() is None:
            return None
        total = 0.0
        for item in self._transactions():
            energy = _coerce_number(item.get("totalEnergy"))
            if energy is not None:
                total += float(energy)
        return round(total, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return per-card session statistics (without the card number)."""
        card = self._card()
        if card is None:
            return {}
        transactions = self._transactions()
        last = transactions[0] if transactions else None
        return {
            "card_number": mask_card_number(card.get("externalId")),
            "label": ((self.coordinator.data or {}).get("card_labels") or {}).get(self._card_key),
            "provider": (card.get("cardProvider") or {}).get("name"),
            "transactions": len(transactions),
            "last_transaction_date": last.get("startDate") if last else None,
            "last_transaction_energy": _coerce_number(last.get("totalEnergy")) if last else None,
        }
