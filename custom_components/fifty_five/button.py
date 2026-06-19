"""Button platform for 50Five EV Charger."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
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
    """Set up 50Five buttons based on a config entry."""
    coordinator: FiftyFiveDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        FiftyFiveStartTransactionButton(coordinator, entry),
        FiftyFiveStopTransactionButton(coordinator, entry),
    ])


class FiftyFiveStartTransactionButton(
    CoordinatorEntity[FiftyFiveDataUpdateCoordinator], ButtonEntity
):
    """Representation of a button to start a charging transaction."""

    _attr_has_entity_name = True
    entity_description = ButtonEntityDescription(
        key="start_transaction",
        name="Start Transaction",
        icon="mdi:play-circle",
    )

    def __init__(
        self,
        coordinator: FiftyFiveDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_start_transaction"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"50Five Charger {coordinator.data.get('charge_station_id', '')}",
            manufacturer="50Five",
            model="EV Charger",
        )

    @property
    def available(self) -> bool:
        """Return True if no active transaction (can start)."""
        if not self.coordinator.data:
            return False
        # Check both active_transaction and channel status
        has_active_transaction = self.coordinator.data.get("active_transaction") is not None
        channel_status = self.coordinator.data.get("channel", {}).get("globalStatus", "").lower()
        is_charging = channel_status in ("charging", "occupied", "busy")
        # Only available when NOT charging
        return not has_active_transaction and not is_charging

    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.info("Starting charging transaction")
        result = await self.coordinator.async_start_transaction()
        if result:
            _LOGGER.info("Transaction started successfully")
        else:
            _LOGGER.error("Failed to start transaction")


class FiftyFiveStopTransactionButton(
    CoordinatorEntity[FiftyFiveDataUpdateCoordinator], ButtonEntity
):
    """Representation of a button to stop a charging transaction."""

    _attr_has_entity_name = True
    entity_description = ButtonEntityDescription(
        key="stop_transaction",
        name="Stop Transaction",
        icon="mdi:stop-circle",
    )

    def __init__(
        self,
        coordinator: FiftyFiveDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_stop_transaction"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"50Five Charger {coordinator.data.get('charge_station_id', '')}",
            manufacturer="50Five",
            model="EV Charger",
        )

    @property
    def available(self) -> bool:
        """Return True if there's an active transaction (can stop)."""
        if not self.coordinator.data:
            return False
        # Check both active_transaction and channel status
        has_active_transaction = self.coordinator.data.get("active_transaction") is not None
        channel_status = self.coordinator.data.get("channel", {}).get("globalStatus", "").lower()
        is_charging = channel_status in ("charging", "occupied", "busy")
        # Available when charging (either by transaction or channel status)
        return has_active_transaction or is_charging

    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.info("Stopping charging transaction")
        result = await self.coordinator.async_stop_transaction()
        if result:
            _LOGGER.info("Transaction stopped successfully")
        else:
            _LOGGER.error("Failed to stop transaction")


