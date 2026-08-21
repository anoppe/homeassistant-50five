"""Select platform for 50Five EV Charger integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FiftyFiveDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

NONE_OPTION = "None (No default card)"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up 50Five select entities."""
    coordinator: FiftyFiveDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    async_add_entities([FiftyFiveChargeCardSelect(coordinator, entry)])


class FiftyFiveChargeCardSelect(CoordinatorEntity, SelectEntity):
    """Select entity for choosing default charge card."""

    def __init__(
        self,
        coordinator: FiftyFiveDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_charge_card_select"
        self._attr_name = "Charge Card"
        self._attr_icon = "mdi:credit-card"

    @property
    def device_info(self):
        """Return device info."""
        charge_station_id = self.coordinator.data.get("charge_station_id")
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"50Five Charger {charge_station_id}",
            "manufacturer": "50Five",
            "model": "EV Charger",
        }

    @property
    def options(self) -> list[str]:
        """Return available charge card options."""
        cards = self.coordinator.data.get("charge_cards", [])
        
        options = [NONE_OPTION]
        
        for card in cards:
            external_id = card.get("externalId", "Unknown")
            provider = card.get("cardProvider", {}).get("name", "Unknown")
            state = card.get("state", "")
            
            # Format: "Card 1234567890 (50Five)"
            option = f"Card {external_id} ({provider})"
            options.append(option)
            
        _LOGGER.debug("Available card options: %s", options)
        return options

    @property
    def current_option(self) -> str:
        """Return the currently selected option."""
        selected_card_id = self.coordinator.selected_card_id
        
        if not selected_card_id:
            return NONE_OPTION
        
        cards = self.coordinator.data.get("charge_cards", [])
        selected_card = next((c for c in cards if c["id"] == selected_card_id), None)
        
        if selected_card:
            external_id = selected_card.get("externalId", "Unknown")
            provider = selected_card.get("cardProvider", {}).get("name", "Unknown")
            return f"Card {external_id} ({provider})"
        
        # If selected card not found in current cards, reset to None
        return NONE_OPTION

    async def async_select_option(self, option: str) -> None:
        """Handle option selection."""
        if option == NONE_OPTION:
            self.coordinator.set_selected_card(None)
            _LOGGER.info("Default charge card cleared")
        else:
            # Parse the option to extract card ID
            # Option format: "Card 1234567890 (50Five)"
            cards = self.coordinator.data.get("charge_cards", [])
            
            # Extract externalId from option string
            for card in cards:
                external_id = card.get("externalId", "")
                provider = card.get("cardProvider", {}).get("name", "")
                expected_option = f"Card {external_id} ({provider})"
                
                if expected_option == option:
                    card_id = card["id"]
                    self.coordinator.set_selected_card(card_id)
                    _LOGGER.info("Default charge card set to: %s (ID: %s)", option, card_id)
                    break
        
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        selected_card_id = self.coordinator.selected_card_id
        
        if not selected_card_id:
            return {}
        
        cards = self.coordinator.data.get("charge_cards", [])
        selected_card = next((c for c in cards if c["id"] == selected_card_id), None)
        
        if selected_card:
            return {
                "card_id": selected_card.get("id"),
                "external_id": selected_card.get("externalId"),
                "provider": selected_card.get("cardProvider", {}).get("name"),
                "type": selected_card.get("type"),
                "state": selected_card.get("state"),
                "roaming": selected_card.get("roaming"),
            }
        
        return {}
