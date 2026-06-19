"""Data update coordinator for 50Five EV Charger."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FiftyFiveApiClient, FiftyFiveApiError, FiftyFiveAuthError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Charging history is fetched less frequently (every 10 minutes)
HISTORY_UPDATE_INTERVAL = timedelta(minutes=10)

# Rapid polling settings after start/stop actions
RAPID_POLL_INTERVAL = 5  # seconds
RAPID_POLL_TIMEOUT = 20  # seconds (max time to poll rapidly)


class FiftyFiveDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching 50Five data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: FiftyFiveApiClient,
        update_interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.client = client
        self._last_history_update: datetime | None = None
        self._cached_history: list[dict[str, Any]] = []
        self._pending_action: bool = False
        self._rapid_poll_task: asyncio.Task | None = None
        _LOGGER.debug(
            "Coordinator initialized with update interval: %s seconds, history interval: %s seconds",
            update_interval.total_seconds(),
            HISTORY_UPDATE_INTERVAL.total_seconds(),
        )

    @property
    def is_pending_action(self) -> bool:
        """Return True if waiting for a state change after action."""
        return self._pending_action

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API."""
        _LOGGER.debug("Coordinator: Starting data update...")
        try:
            # Fetch real-time data (status, active transaction, etc.)
            data = await self.client.get_realtime_data()

            # Check if we need to update charging history
            now = dt_util.utcnow()
            should_update_history = (
                self._last_history_update is None
                or (now - self._last_history_update) >= HISTORY_UPDATE_INTERVAL
            )

            if should_update_history:
                _LOGGER.debug("Coordinator: Fetching charging history (interval reached)")
                try:
                    self._cached_history = await self.client.get_charging_history()
                    self._last_history_update = now
                    _LOGGER.debug("Coordinator: Charging history updated, %d transactions", len(self._cached_history))
                except FiftyFiveApiError as err:
                    _LOGGER.warning("Coordinator: Failed to fetch charging history: %s", err)
                    # Keep using cached history on error
            else:
                time_until_next = HISTORY_UPDATE_INTERVAL - (now - self._last_history_update)
                _LOGGER.debug(
                    "Coordinator: Using cached charging history (%d transactions), next update in %s",
                    len(self._cached_history),
                    time_until_next,
                )

            # Add cached history to the data
            data["charging_history"] = self._cached_history

            _LOGGER.debug("Coordinator: Data update successful")
            return data
        except FiftyFiveAuthError as err:
            _LOGGER.debug("Coordinator: Auth error, attempting re-authentication: %s", err)
            # Try to re-authenticate once
            try:
                await self.client.authenticate()
                data = await self.client.get_realtime_data()
                data["charging_history"] = self._cached_history
                _LOGGER.debug("Coordinator: Data update successful after re-auth")
                return data
            except FiftyFiveApiError as auth_err:
                _LOGGER.debug("Coordinator: Re-authentication failed: %s", auth_err)
                raise UpdateFailed(f"Authentication failed: {auth_err}") from auth_err
        except FiftyFiveApiError as err:
            _LOGGER.debug("Coordinator: Data update failed: %s", err)
            raise UpdateFailed(f"Error fetching data: {err}") from err

    async def _rapid_poll_until_state_change(self, expected_charging: bool) -> None:
        """Poll rapidly until the charging state matches expected or timeout."""
        _LOGGER.debug("Coordinator: Starting rapid polling, expecting charging=%s", expected_charging)
        start_time = dt_util.utcnow()
        
        while (dt_util.utcnow() - start_time).total_seconds() < RAPID_POLL_TIMEOUT:
            await asyncio.sleep(RAPID_POLL_INTERVAL)
            
            try:
                await self.async_request_refresh()
                
                # Check if state has changed to expected
                if self.data:
                    has_active = self.data.get("active_transaction") is not None
                    channel_status = self.data.get("channel", {}).get("globalStatus", "").lower()
                    is_charging = has_active or channel_status in ("charging", "occupied", "busy")
                    
                    _LOGGER.debug(
                        "Coordinator: Rapid poll check - is_charging=%s, expected=%s",
                        is_charging, expected_charging
                    )
                    
                    if is_charging == expected_charging:
                        _LOGGER.debug("Coordinator: State changed to expected, stopping rapid poll")
                        break
            except Exception as err:
                _LOGGER.debug("Coordinator: Rapid poll error: %s", err)
        
        self._pending_action = False
        # Notify listeners that pending state has changed
        self.async_update_listeners()
        _LOGGER.debug("Coordinator: Rapid polling complete")

    async def async_start_transaction(self, card: str = "") -> bool:
        """Start a charging transaction."""
        _LOGGER.debug("Coordinator: Start transaction requested (card: %s)", card or "(none)")
        
        # Cancel any existing rapid poll task
        if self._rapid_poll_task and not self._rapid_poll_task.done():
            self._rapid_poll_task.cancel()
        
        self._pending_action = True
        self.async_update_listeners()
        
        result = await self.client.start_transaction(card)
        _LOGGER.debug("Coordinator: Start transaction result: %s", result)
        
        if result:
            _LOGGER.debug("Coordinator: Starting rapid polling after transaction start")
            self._last_history_update = None
            # Start rapid polling in background
            self._rapid_poll_task = asyncio.create_task(
                self._rapid_poll_until_state_change(expected_charging=True)
            )
        else:
            self._pending_action = False
            self.async_update_listeners()
        
        return result

    async def async_stop_transaction(self) -> bool:
        """Stop an active charging transaction."""
        _LOGGER.debug("Coordinator: Stop transaction requested")
        
        # Cancel any existing rapid poll task
        if self._rapid_poll_task and not self._rapid_poll_task.done():
            self._rapid_poll_task.cancel()
        
        self._pending_action = True
        self.async_update_listeners()
        
        result = await self.client.stop_transaction()
        _LOGGER.debug("Coordinator: Stop transaction result: %s", result)
        
        if result:
            _LOGGER.debug("Coordinator: Starting rapid polling after transaction stop")
            self._last_history_update = None
            # Start rapid polling in background
            self._rapid_poll_task = asyncio.create_task(
                self._rapid_poll_until_state_change(expected_charging=False)
            )
        else:
            self._pending_action = False
            self.async_update_listeners()
        
        return result

