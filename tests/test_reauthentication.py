"""Tests for authentication recovery and credential replacement."""

import json
import tempfile
import unittest
from datetime import timedelta
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.fifty_five.api import (
    FiftyFiveApiClient,
    FiftyFiveApiError,
    FiftyFiveAuthError,
)
from custom_components.fifty_five.config_flow import ConfigFlow
from custom_components.fifty_five.const import (
    CONF_CHANNEL_ID,
    CONF_CHARGE_STATION_ID,
    CONF_CUSTOMER_ID,
)
from custom_components.fifty_five.coordinator import FiftyFiveDataUpdateCoordinator


class ApiAuthenticationTest(unittest.IsolatedAsyncioTestCase):
    async def test_http_auth_errors_are_recognized_without_json(self) -> None:
        for status in (401, 403):
            with self.subTest(status=status):
                response = MagicMock()
                response.status = status
                response.text = AsyncMock(return_value="Access denied")
                response.raise_for_status.side_effect = aiohttp.ClientResponseError(
                    MagicMock(), (), status=status
                )
                session = MagicMock()
                session.post.return_value.__aenter__ = AsyncMock(return_value=response)
                client = FiftyFiveApiClient(session, "old@example.com", "old-password")
                client._access_token = "expired"

                with self.assertRaises(FiftyFiveAuthError):
                    await client._execute_query("query")
                self.assertIsNone(client._access_token)

    async def test_graphql_auth_code_is_recognized(self) -> None:
        response = MagicMock()
        response.status = 200
        response.text = AsyncMock(
            return_value=json.dumps(
                {"errors": [{"message": "Login required", "extensions": {"code": "UNAUTHENTICATED"}}]}
            )
        )
        session = MagicMock()
        session.post.return_value.__aenter__ = AsyncMock(return_value=response)
        client = FiftyFiveApiClient(session, "old@example.com", "old-password")
        client._access_token = "expired"

        with self.assertRaises(FiftyFiveAuthError):
            await client._execute_query("query")
        self.assertIsNone(client._access_token)

    async def test_invalid_credentials_message_is_recognized(self) -> None:
        response = MagicMock()
        response.status = 200
        response.text = AsyncMock(
            return_value=json.dumps({"errors": [{"message": "Invalid credentials"}]})
        )
        session = MagicMock()
        session.post.return_value.__aenter__ = AsyncMock(return_value=response)
        client = FiftyFiveApiClient(session, "old@example.com", "old-password")
        with self.assertRaises(FiftyFiveAuthError):
            await client.authenticate()

    async def test_server_failure_is_not_authentication_failure(self) -> None:
        response = MagicMock()
        response.status = 503
        response.text = AsyncMock(return_value="Service unavailable")
        response.raise_for_status.side_effect = aiohttp.ClientResponseError(
            MagicMock(), (), status=503
        )
        session = MagicMock()
        session.post.return_value.__aenter__ = AsyncMock(return_value=response)
        client = FiftyFiveApiClient(session, "old@example.com", "old-password")
        client._access_token = "valid"
        with self.assertRaises(FiftyFiveApiError) as raised:
            await client._execute_query("query")
        self.assertNotIsInstance(raised.exception, FiftyFiveAuthError)

    async def test_connection_failure_is_not_authentication_failure(self) -> None:
        session = MagicMock()
        session.post.return_value.__aenter__.side_effect = aiohttp.ClientConnectionError()
        client = FiftyFiveApiClient(session, "old@example.com", "old-password")
        client._access_token = "valid"
        with self.assertRaises(FiftyFiveApiError) as raised:
            await client._execute_query("query")
        self.assertNotIsInstance(raised.exception, FiftyFiveAuthError)

    async def test_timeout_is_not_authentication_failure(self) -> None:
        session = MagicMock()
        session.post.return_value.__aenter__.side_effect = TimeoutError()
        client = FiftyFiveApiClient(session, "old@example.com", "old-password")
        client._access_token = "valid"
        with self.assertRaises(FiftyFiveApiError) as raised:
            await client._execute_query("query")
        self.assertNotIsInstance(raised.exception, FiftyFiveAuthError)
        self.assertEqual(client._access_token, "valid")


class HomeAssistantTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.hass = HomeAssistant(directory.name)
        self.entry = ConfigEntry(
            entry_id="existing-entry",
            domain="fifty_five",
            version=1,
            minor_version=1,
            source="user",
            state=ConfigEntryState.SETUP_IN_PROGRESS,
            discovery_keys=MappingProxyType({}),
            subentries_data=[],
            unique_id="station_channel",
            title="Existing charger",
            data={
                CONF_EMAIL: "old@example.com",
                CONF_PASSWORD: "old-password",
                CONF_CUSTOMER_ID: "old-customer",
                CONF_CHARGE_STATION_ID: "station",
                CONF_CHANNEL_ID: "channel",
            },
            options={"default_card_id": "card"},
        )


class CoordinatorAuthenticationTest(HomeAssistantTest):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.client = MagicMock()
        self.client.authenticate = AsyncMock(return_value=True)
        self.client.get_realtime_data = AsyncMock(return_value={"channel": {}})
        self.client.get_charging_history = AsyncMock(return_value=[])
        self.coordinator = FiftyFiveDataUpdateCoordinator(
            self.hass, self.client, timedelta(seconds=30)
        )

    async def test_failed_credentials_request_reauthentication(self) -> None:
        self.client.get_realtime_data.side_effect = FiftyFiveAuthError("Expired")
        self.client.authenticate.side_effect = FiftyFiveAuthError("Invalid credentials")
        with self.assertRaises(ConfigEntryAuthFailed):
            await self.coordinator._async_update_data()

    async def test_expired_token_recovers_without_reauthentication(self) -> None:
        self.client.get_realtime_data.side_effect = [
            FiftyFiveAuthError("Expired"),
            {"channel": {}},
        ]
        data = await self.coordinator._async_update_data()
        self.assertEqual(data["charging_history"], [])
        self.client.authenticate.assert_awaited_once()

    async def test_network_error_during_retry_does_not_request_reauthentication(self) -> None:
        self.client.get_realtime_data.side_effect = FiftyFiveAuthError("Expired")
        self.client.authenticate.side_effect = FiftyFiveApiError("Offline")
        with self.assertRaises(UpdateFailed):
            await self.coordinator._async_update_data()

    async def test_history_authentication_failure_is_not_swallowed(self) -> None:
        self.client.get_charging_history.side_effect = FiftyFiveAuthError("Expired")
        self.client.authenticate.side_effect = FiftyFiveAuthError("Invalid credentials")
        with self.assertRaises(ConfigEntryAuthFailed):
            await self.coordinator._async_update_data()

    async def test_history_network_failure_keeps_cached_history(self) -> None:
        self.coordinator._cached_history = [{"id": "transaction"}]
        self.client.get_charging_history.side_effect = FiftyFiveApiError("Offline")
        with self.assertLogs(
            "custom_components.fifty_five.coordinator", level="WARNING"
        ):
            data = await self.coordinator._async_update_data()
        self.assertEqual(data["charging_history"], [{"id": "transaction"}])

    async def test_coordinator_has_explicit_config_entry(self) -> None:
        coordinator = FiftyFiveDataUpdateCoordinator(
            self.hass, self.client, timedelta(seconds=30), config_entry=self.entry
        )
        self.assertIs(coordinator.config_entry, self.entry)

    async def test_runtime_refresh_requests_home_assistant_reauthentication(self) -> None:
        coordinator = FiftyFiveDataUpdateCoordinator(
            self.hass, self.client, timedelta(seconds=30), config_entry=self.entry
        )
        self.client.get_realtime_data.side_effect = FiftyFiveAuthError("Expired")
        self.client.authenticate.side_effect = FiftyFiveAuthError("Invalid credentials")
        coordinator.async_add_listener(lambda: None)
        coordinator._unsub_refresh = None
        with patch.object(ConfigEntry, "async_start_reauth_if_available") as reauth:
            with self.assertLogs(
                "custom_components.fifty_five.coordinator", level="ERROR"
            ):
                await coordinator.async_refresh()
        reauth.assert_called_once_with(self.hass)
        self.assertFalse(coordinator.last_update_success)
        self.assertIsInstance(coordinator.last_exception, ConfigEntryAuthFailed)
        # Polling must stop so the stored password is not retried every 30 seconds.
        self.assertIsNone(coordinator._unsub_refresh)
        self.assertEqual(self.client.authenticate.await_count, 1)

    async def test_setup_refresh_propagates_authentication_failure(self) -> None:
        coordinator = FiftyFiveDataUpdateCoordinator(
            self.hass, self.client, timedelta(seconds=30), config_entry=self.entry
        )
        self.client.get_realtime_data.side_effect = FiftyFiveAuthError("Expired")
        self.client.authenticate.side_effect = FiftyFiveAuthError("Invalid credentials")
        with self.assertRaises(ConfigEntryAuthFailed):
            await coordinator.async_config_entry_first_refresh()


class ReauthenticationFlowTest(HomeAssistantTest):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.hass.config_entries = MagicMock()
        self.hass.config_entries.async_get_known_entry.return_value = self.entry
        self.flow = ConfigFlow()
        self.flow.hass = self.hass
        self.flow.context = {"source": "reauth", "entry_id": self.entry.entry_id}
        self.client = MagicMock()
        self.client.authenticate = AsyncMock(return_value=True)
        self.client.customer_id = "new-customer"
        self.client.get_charge_station_overview = AsyncMock(return_value={"id": "station"})
        self.factory = self.enterContext(
            patch("custom_components.fifty_five.config_flow.FiftyFiveApiClient", return_value=self.client)
        )
        self.enterContext(
            patch("custom_components.fifty_five.config_flow.async_get_clientsession", return_value=MagicMock())
        )

    async def test_reauth_shows_credentials_form(self) -> None:
        result = await self.flow.async_step_reauth(self.entry.data)
        self.assertEqual(result["step_id"], "reauth_confirm")
        schema = result["data_schema"].schema
        self.assertEqual({key.schema for key in schema}, {CONF_EMAIL, CONF_PASSWORD})

    async def test_valid_credentials_update_and_reload_existing_entry(self) -> None:
        result = await self.flow.async_step_reauth_confirm(
            {CONF_EMAIL: "new@example.com", CONF_PASSWORD: "new-password"}
        )
        self.assertEqual(result["reason"], "reauth_successful")
        update = self.hass.config_entries.async_update_entry.call_args.kwargs
        self.assertIs(update["entry"], self.entry)
        self.assertEqual(
            update["data"],
            self.entry.data | {
                CONF_EMAIL: "new@example.com",
                CONF_PASSWORD: "new-password",
                CONF_CUSTOMER_ID: "new-customer",
            },
        )
        self.client.authenticate.assert_awaited_once()
        self.client.get_charge_station_overview.assert_awaited_once()
        self.hass.config_entries.async_schedule_reload.assert_called_once_with("existing-entry")
        self.assertEqual(self.entry.unique_id, "station_channel")
        self.assertEqual(self.entry.options, {"default_card_id": "card"})

    async def test_invalid_credentials_do_not_update_entry(self) -> None:
        self.client.authenticate.side_effect = FiftyFiveAuthError("Invalid credentials")
        await self._assert_reauth_error("invalid_auth")

    async def test_network_failure_does_not_update_entry(self) -> None:
        self.client.authenticate.side_effect = FiftyFiveApiError("Offline")
        await self._assert_reauth_error("cannot_connect")

    async def test_missing_customer_does_not_update_entry(self) -> None:
        self.client.customer_id = None
        await self._assert_reauth_error("no_customer_id")

    async def test_charger_access_failure_does_not_update_entry(self) -> None:
        self.client.get_charge_station_overview.side_effect = FiftyFiveApiError("No access")
        await self._assert_reauth_error("cannot_connect")

    async def test_missing_charger_does_not_update_entry(self) -> None:
        self.client.get_charge_station_overview.return_value = None
        await self._assert_reauth_error("cannot_connect")

    async def _assert_reauth_error(self, expected: str) -> None:
        result = await self.flow.async_step_reauth_confirm(
            {CONF_EMAIL: "new@example.com", CONF_PASSWORD: "new-password"}
        )
        self.assertEqual(result["errors"], {"base": expected})
        self.hass.config_entries.async_update_entry.assert_not_called()
        self.hass.config_entries.async_schedule_reload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
