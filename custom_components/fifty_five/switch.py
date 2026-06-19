"""Switch platform for 50Five EV Charger."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FiftyFiveDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up 50Five switches based on a config entry."""
    coordinator: FiftyFiveDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        FiftyFiveChargingSwitch(coordinator, entry),
    ])


class FiftyFiveChargingSwitch(
    CoordinatorEntity[FiftyFiveDataUpdateCoordinator], SwitchEntity
):
    """Representation of a switch to control charging."""

    _attr_has_entity_name = True
    _attr_translation_key = "charging"
    entity_description = SwitchEntityDescription(
        key="charging",
        name="Charging",
    )

    def __init__(
        self,
        coordinator: FiftyFiveDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_charging"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"50Five Charger {coordinator.data.get('charge_station_id', '')}",
            manufacturer="50Five",
            model="EV Charger",
        )

    @property
    def icon(self) -> str:
        """Return the icon based on state."""
        if self.coordinator.is_pending_action:
            return "mdi:sync"
        return "mdi:ev-station" if self.is_on else "mdi:ev-plug-type2"

    @property
    def is_on(self) -> bool:
        """Return True if charging is active."""
        if not self.coordinator.data:
            return False
        # Check both active_transaction and channel status
        has_active_transaction = self.coordinator.data.get("active_transaction") is not None
        channel_status = self.coordinator.data.get("channel", {}).get("globalStatus", "").lower()
        is_charging = channel_status in ("charging", "occupied", "busy")
        return has_active_transaction or is_charging

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {
            "action": "Stop Charging" if self.is_on else "Start Charging",
            "status": "Charging" if self.is_on else "Not Charging",
        }

        if self.coordinator.data:
            channel_status = self.coordinator.data.get("channel", {}).get("globalStatus")
            if channel_status:
                attrs["channel_status"] = channel_status

            active_tx = self.coordinator.data.get("active_transaction")
            if active_tx:
                attrs["energy_delivered"] = active_tx.get("energyDelivered")
                attrs["duration_minutes"] = active_tx.get("durationCharging")
                attrs["current_cost"] = active_tx.get("totalAmount")

        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on charging (start transaction)."""
        _LOGGER.info("Starting charging transaction via switch")
        result = await self.coordinator.async_start_transaction()
        if result:
            _LOGGER.info("Transaction start command sent, waiting for confirmation...")
        else:
            _LOGGER.error("Failed to start transaction")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off charging (stop transaction)."""
        _LOGGER.info("Stopping charging transaction via switch")
        result = await self.coordinator.async_stop_transaction()
        if result:
            _LOGGER.info("Transaction stop command sent, waiting for confirmation...")
        else:
            _LOGGER.error("Failed to stop transaction")

