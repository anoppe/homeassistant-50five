"""Select platform for 50Five EV Charger integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_DEFAULT_CARD_ID, mask_card_number
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

    def _card_options(self) -> dict[str, dict[str, Any]]:
        """Map display labels to cards; labels never contain the full card number."""
        cards = self.coordinator.data.get("charge_cards", []) or []
        options: dict[str, dict[str, Any]] = {}
        for index, card in enumerate(cards, start=1):
            provider = (card.get("cardProvider") or {}).get("name") or "Unknown"
            label = f"Card {index} ({provider}, {mask_card_number(card.get('externalId'))})"
            options[label] = card
        return options

    def _selected_card(self) -> tuple[str, dict[str, Any]] | None:
        """Return the label and card matching the coordinator's selected card."""
        selected_card_id = self.coordinator.selected_card_id
        if not selected_card_id:
            return None
        # Match externalId, with a fallback for legacy selections stored by internal id.
        for label, card in self._card_options().items():
            if selected_card_id in (card.get("externalId"), card.get("id")):
                return label, card
        return None

    @property
    def options(self) -> list[str]:
        """Return available charge card options."""
        options = [NONE_OPTION, *self._card_options()]
        _LOGGER.debug("Available card options: %s", options)
        return options

    @property
    def current_option(self) -> str:
        """Return the currently selected option."""
        selected = self._selected_card()
        return selected[0] if selected else NONE_OPTION

    async def async_select_option(self, option: str) -> None:
        """Handle option selection."""
        selected_card_id: str | None = None

        if option == NONE_OPTION:
            _LOGGER.info("Default charge card cleared")
        else:
            card = self._card_options().get(option)
            if card is None or not card.get("externalId"):
                _LOGGER.warning("Selected charge card option not found in current card list: %s", option)
                return
            selected_card_id = card["externalId"]
            _LOGGER.info("Default charge card set to: %s", option)

        updated_options = dict(self._entry.options)
        if selected_card_id is None:
            updated_options.pop(CONF_DEFAULT_CARD_ID, None)
        else:
            updated_options[CONF_DEFAULT_CARD_ID] = selected_card_id

        self.hass.config_entries.async_update_entry(self._entry, options=updated_options)
        self.coordinator.set_selected_card(selected_card_id)

        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes (without the card number)."""
        selected = self._selected_card()
        if not selected:
            return {}

        card = selected[1]
        return {
            "card_number": mask_card_number(card.get("externalId")),
            "provider": (card.get("cardProvider") or {}).get("name"),
            "type": card.get("type"),
            "state": card.get("state"),
            "roaming": card.get("roaming"),
        }
