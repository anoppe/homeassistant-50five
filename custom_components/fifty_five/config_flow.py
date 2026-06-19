"""Config flow for 50Five EV Charger integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import FiftyFiveApiClient, FiftyFiveApiError, FiftyFiveAuthError
from .const import DOMAIN, CONF_CHARGE_STATION_ID, CONF_CHANNEL_ID, CONF_CUSTOMER_ID

_LOGGER = logging.getLogger(__name__)

# Step 1: Only ask for credentials
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for 50Five EV Charger."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._email: str | None = None
        self._password: str | None = None
        self._customer_id: str | None = None
        self._charge_stations: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - ask for credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]

            try:
                session = async_get_clientsession(self.hass)
                client = FiftyFiveApiClient(
                    session=session,
                    email=self._email,
                    password=self._password,
                )

                # Authenticate and get customer ID
                await client.authenticate()
                self._customer_id = client.customer_id

                if not self._customer_id:
                    errors["base"] = "no_customer_id"
                else:
                    # Try to discover charge stations
                    try:
                        self._charge_stations = await client.discover_charge_stations()
                    except FiftyFiveApiError:
                        # If discovery fails, we'll need to proceed without it
                        self._charge_stations = []

                    if len(self._charge_stations) == 0:
                        # No charge stations found - need to enter manually
                        return await self.async_step_manual()
                    elif len(self._charge_stations) == 1:
                        # Only one charge station - auto-select it
                        station = self._charge_stations[0]
                        channels = station.get("channels", [])
                        if len(channels) >= 1:
                            return await self._create_entry(
                                station["id"],
                                channels[0]["id"],
                                station.get("name", station["id"]),
                            )
                        else:
                            # No channels, enter manually
                            return await self.async_step_manual()
                    else:
                        # Multiple charge stations - let user choose
                        return await self.async_step_select_station()

            except FiftyFiveAuthError:
                errors["base"] = "invalid_auth"
            except FiftyFiveApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_select_station(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle selecting a charge station when multiple are available."""
        if user_input is not None:
            selected = user_input["charge_station"]
            # Find the selected station
            for station in self._charge_stations:
                station_label = f"{station.get('name', 'Station')} ({station['id']})"
                if station_label == selected:
                    channels = station.get("channels", [])
                    if len(channels) >= 1:
                        return await self._create_entry(
                            station["id"],
                            channels[0]["id"],
                            station.get("name", station["id"]),
                        )
                    break
            # If no match or no channels, go to manual entry
            return await self.async_step_manual()

        # Build options for selection
        station_options = [
            f"{station.get('name', 'Station')} ({station['id']})"
            for station in self._charge_stations
        ]

        return self.async_show_form(
            step_id="select_station",
            data_schema=vol.Schema(
                {
                    vol.Required("charge_station"): vol.In(station_options),
                }
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual entry of charge station details."""
        errors: dict[str, str] = {}

        if user_input is not None:
            charge_station_id = user_input[CONF_CHARGE_STATION_ID]
            channel_id = user_input[CONF_CHANNEL_ID]

            try:
                session = async_get_clientsession(self.hass)
                client = FiftyFiveApiClient(
                    session=session,
                    email=self._email,
                    password=self._password,
                    charge_station_id=charge_station_id,
                    channel_id=channel_id,
                    customer_id=self._customer_id,
                )

                if await client.test_connection():
                    return await self._create_entry(
                        charge_station_id,
                        channel_id,
                        f"Charger {charge_station_id}",
                    )
                else:
                    errors["base"] = "cannot_connect"
            except FiftyFiveAuthError:
                errors["base"] = "invalid_auth"
            except FiftyFiveApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CHARGE_STATION_ID): str,
                    vol.Required(CONF_CHANNEL_ID): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "info": "Enter your charge station and channel IDs manually."
            },
        )

    async def _create_entry(
        self, charge_station_id: str, channel_id: str, name: str
    ) -> FlowResult:
        """Create the config entry."""
        await self.async_set_unique_id(f"{charge_station_id}_{channel_id}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"50Five {name}",
            data={
                CONF_EMAIL: self._email,
                CONF_PASSWORD: self._password,
                CONF_CHARGE_STATION_ID: charge_station_id,
                CONF_CHANNEL_ID: channel_id,
                CONF_CUSTOMER_ID: self._customer_id,
            },
        )
