"""API Client for 50Five EV Charger."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

import aiohttp

from .const import (
    API_URL,
    APPLICATION_ID,
    LOGIN_MUTATION,
    GET_CHARGE_STATION_OVERVIEW,
    GET_CHARGE_STATION_CHANNEL,
    LMS_ACTIVE_TRANSACTION,
    START_TRANSACTION_MUTATION,
    STOP_TRANSACTION_MUTATION,
    ACTIVE_RESERVATION,
    GET_CHARGING_HISTORY,
    GET_CUSTOMER_WITH_CHARGE_STATIONS,
    GET_CUSTOMER_CHARGE_CARDS,
)

_LOGGER = logging.getLogger(__name__)


def _sanitize_payload_for_logging(payload: dict[str, Any]) -> dict[str, Any]:
    """Sanitize payload for logging by masking sensitive data."""
    sanitized = payload.copy()
    if "variables" in sanitized:
        variables = sanitized["variables"].copy()
        if "password" in variables:
            variables["password"] = "***REDACTED***"
        if "email" in variables:
            # Partially mask email
            email = variables["email"]
            if "@" in email:
                local, domain = email.rsplit("@", 1)
                variables["email"] = f"{local[:2]}***@{domain}"
        sanitized["variables"] = variables
    return sanitized


def _sanitize_response_for_logging(data: dict[str, Any]) -> dict[str, Any]:
    """Sanitize response for logging by masking sensitive data."""
    sanitized = data.copy()
    if "data" in sanitized and "login" in sanitized.get("data", {}):
        login_data = sanitized["data"]["login"].copy() if sanitized["data"]["login"] else {}
        if "access_token" in login_data:
            token = login_data["access_token"]
            login_data["access_token"] = f"{token[:10]}...***REDACTED***" if token else None
        sanitized["data"] = {"login": login_data}
    return sanitized


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode JWT token and extract payload."""
    try:
        # JWT format: header.payload.signature
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        
        # Decode the payload (second part)
        payload = parts[1]
        # Add padding if needed
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception as err:
        _LOGGER.debug("Failed to decode JWT payload: %s", err)
        return {}


class FiftyFiveApiError(Exception):
    """Exception for API errors."""


class FiftyFiveAuthError(FiftyFiveApiError):
    """Exception for authentication errors."""


class FiftyFiveApiClient:
    """API client for 50Five EV Charger."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        charge_station_id: str | None = None,
        channel_id: str | None = None,
        customer_id: str | None = None,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._email = email
        self._password = password
        self._charge_station_id = charge_station_id
        self._channel_id = channel_id
        self._customer_id = customer_id
        self._access_token: str | None = None

    @property
    def customer_id(self) -> str | None:
        """Return the customer ID."""
        return self._customer_id

    @property
    def charge_station_id(self) -> str | None:
        """Return the charge station ID."""
        return self._charge_station_id

    @property
    def channel_id(self) -> str | None:
        """Return the channel ID."""
        return self._channel_id

    def set_charge_station(self, charge_station_id: str, channel_id: str) -> None:
        """Set the charge station and channel IDs."""
        self._charge_station_id = charge_station_id
        self._channel_id = channel_id

    async def _execute_query(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        """Execute a GraphQL query."""
        # Always include plugz-application-id header for all requests
        headers = {
            "Content-Type": "application/json",
            "plugz-application-id": APPLICATION_ID,
        }

        _LOGGER.debug("Using APPLICATION_ID: %s", APPLICATION_ID)

        if authenticated:
            if not self._access_token:
                await self.authenticate()
            headers["Authorization"] = f"Bearer {self._access_token}"

        payload = {
            "query": query,
            "variables": variables or {},
        }

        if operation_name:
            payload["operationName"] = operation_name

        # Debug log the request (with sanitized auth header)
        sanitized_payload = _sanitize_payload_for_logging(payload)
        sanitized_headers = {
            k: (f"{v[:20]}..." if k == "Authorization" and v else v)
            for k, v in headers.items()
        }
        _LOGGER.debug(
            ">>> REQUEST [%s] to %s",
            operation_name or "unnamed",
            API_URL,
        )
        _LOGGER.debug(">>> Headers: %s", sanitized_headers)
        _LOGGER.debug(">>> Payload: %s", json.dumps(sanitized_payload, indent=2))


        try:
            async with self._session.post(
                API_URL, json=payload, headers=headers
            ) as response:
                status_code = response.status
                response_text = await response.text()

                _LOGGER.debug(
                    "<<< RESPONSE [%s] Status: %s",
                    operation_name or "unnamed",
                    status_code,
                )

                try:
                    data = json.loads(response_text)
                    sanitized_response = _sanitize_response_for_logging(data)
                    _LOGGER.debug("<<< Body: %s", json.dumps(sanitized_response, indent=2))
                except json.JSONDecodeError:
                    _LOGGER.debug("<<< Body (raw): %s", response_text[:500])
                    response.raise_for_status()
                    raise FiftyFiveApiError(f"Invalid JSON response: {response_text[:100]}")

                response.raise_for_status()

                if "errors" in data:
                    error_message = data["errors"][0].get("message", "Unknown error")
                    _LOGGER.debug("<<< GraphQL Error: %s", error_message)
                    if "unauthorized" in error_message.lower() or "unauthenticated" in error_message.lower():
                        # Token might be expired, try to re-authenticate
                        self._access_token = None
                        raise FiftyFiveAuthError(error_message)
                    raise FiftyFiveApiError(error_message)

                return data.get("data", {})
        except aiohttp.ClientError as err:
            _LOGGER.debug("<<< REQUEST FAILED [%s]: %s", operation_name or "unnamed", err)
            raise FiftyFiveApiError(f"Request failed: {err}") from err

    async def authenticate(self) -> bool:
        """Authenticate with the API and extract customer ID from JWT."""
        _LOGGER.debug("Attempting authentication for user %s***", self._email[:3] if self._email else "unknown")
        try:
            data = await self._execute_query(
                query=LOGIN_MUTATION,
                variables={"email": self._email, "password": self._password},
                operation_name="Login",
                authenticated=False,
            )

            login_data = data.get("login")
            if login_data and login_data.get("access_token"):
                self._access_token = login_data["access_token"]
                expires_in = login_data.get("expires_in", "unknown")
                
                # Extract customer ID from JWT payload
                jwt_payload = _decode_jwt_payload(self._access_token)
                external_api = jwt_payload.get("external_api", {})
                if external_api.get("customerId"):
                    self._customer_id = str(external_api["customerId"])
                    _LOGGER.debug("Extracted customer ID from JWT: %s", self._customer_id)
                
                _LOGGER.debug(
                    "Successfully authenticated with 50Five API (token expires in: %s)",
                    expires_in,
                )
                return True

            _LOGGER.debug("Authentication failed: No access token in response")
            raise FiftyFiveAuthError("No access token in response")
        except aiohttp.ClientError as err:
            _LOGGER.debug("Authentication request failed: %s", err)
            raise FiftyFiveAuthError(f"Authentication failed: {err}") from err

    async def discover_charge_stations(self) -> list[dict[str, Any]]:
        """Discover charge stations for the authenticated user."""
        _LOGGER.debug("Discovering charge stations for authenticated user")
        data = await self._execute_query(
            query=GET_CUSTOMER_WITH_CHARGE_STATIONS,
            variables={},
            operation_name="GetCustomerChargeStations",
        )
        
        charge_stations = data.get("getCustomerChargeStations", [])
        _LOGGER.debug("Discovered %d charge stations", len(charge_stations))
        return charge_stations

    async def get_charge_cards(self) -> list[dict[str, Any]]:
        """Get charge cards for the authenticated user."""
        if not self._customer_id:
            await self.authenticate()
        
        if not self._customer_id:
            raise FiftyFiveApiError("No customer ID available for fetching charge cards")
        
        _LOGGER.debug("Fetching charge cards for customer: %s", self._customer_id)
        data = await self._execute_query(
            query=GET_CUSTOMER_CHARGE_CARDS,
            variables={"getCustomerByIdId": self._customer_id},
            operation_name="GetCustomerChargecards",
        )
        
        customer = data.get("getCustomerById", {})
        cards = customer.get("cards", [])
        _LOGGER.debug("Found %d charge cards", len(cards))
        return cards

    async def get_charge_station_overview(self) -> dict[str, Any]:
        """Get the charge station overview."""
        _LOGGER.debug("Fetching charge station overview for station: %s", self._charge_station_id)
        data = await self._execute_query(
            query=GET_CHARGE_STATION_OVERVIEW,
            variables={"getChargeStationByIdId": self._charge_station_id},
            operation_name="GetChargeStationOverview",
        )
        result = data.get("getChargeStationById", {})
        _LOGGER.debug("Charge station overview result: %s", result)
        return result

    async def get_charge_station_channel(self) -> dict[str, Any]:
        """Get the charge station channel status."""
        _LOGGER.debug(
            "Fetching channel status for station: %s, channel: %s",
            self._charge_station_id,
            self._channel_id,
        )
        data = await self._execute_query(
            query=GET_CHARGE_STATION_CHANNEL,
            variables={
                "chargeStationId": self._charge_station_id,
                "channelId": self._channel_id,
            },
            operation_name="GetChargeStationChannel",
        )
        result = data.get("getChargeStationChannel", {})
        _LOGGER.debug("Channel status result: %s", result)
        return result

    async def get_active_transaction(self) -> dict[str, Any] | None:
        """Get the active transaction."""
        _LOGGER.debug("Fetching active transaction")
        data = await self._execute_query(
            query=LMS_ACTIVE_TRANSACTION,
            operation_name="LmsActiveTransaction",
        )
        result = data.get("lmsActiveTransaction")
        _LOGGER.debug("Active transaction result: %s", result)
        return result

    async def get_active_reservation(self) -> dict[str, Any] | None:
        """Get the active reservation."""
        _LOGGER.debug("Fetching active reservation")
        data = await self._execute_query(
            query=ACTIVE_RESERVATION,
            operation_name="ActiveReservation",
        )
        result = data.get("activeReservation")
        _LOGGER.debug("Active reservation result: %s", result)
        return result

    async def get_charging_history(self, days: int = 30, items_per_page: int = 30) -> list[dict[str, Any]]:
        """Get charging history for the charge station."""
        from datetime import datetime, timedelta, timezone
        
        now = datetime.now(timezone.utc)
        date_from = now - timedelta(days=days)
        
        _LOGGER.debug(
            "Fetching charging history for station: %s, from: %s to: %s",
            self._charge_station_id,
            date_from.isoformat(),
            now.isoformat(),
        )
        
        data = await self._execute_query(
            query=GET_CHARGING_HISTORY,
            variables={
                "getTransactionsFilters": {
                    "dateFrom": date_from.isoformat(),
                    "dateTo": now.isoformat(),
                    "itemsPerPage": items_per_page,
                    "page": 1,
                    "chargeStation": {
                        "id": self._charge_station_id,
                    },
                },
                "sort": {
                    "startDate": "desc",
                },
            },
            operation_name="GetChargingHistory",
        )
        
        transactions = data.get("getTransactions", {})
        items = transactions.get("items", [])
        _LOGGER.debug("Charging history result: %d transactions found", len(items))
        return items

    async def start_transaction(self, card: str = "") -> bool:
        """Start a charging transaction."""
        _LOGGER.debug(
            "Starting transaction on station: %s, channel: %s, card: %s",
            self._charge_station_id,
            self._channel_id,
            card or "(none)",
        )
        try:
            data = await self._execute_query(
                query=START_TRANSACTION_MUTATION,
                variables={
                    "chargeStationId": self._charge_station_id,
                    "channelId": self._channel_id,
                    "card": card,
                },
                operation_name="StartTransaction",
            )
            result = data.get("startTransaction", False)
            _LOGGER.debug("Start transaction result: %s", result)
            return result
        except FiftyFiveApiError as err:
            _LOGGER.error("Failed to start transaction: %s", err)
            return False

    async def stop_transaction(self) -> bool:
        """Stop an active charging transaction."""
        _LOGGER.debug(
            "Stopping transaction on station: %s, channel: %s",
            self._charge_station_id,
            self._channel_id,
        )
        try:
            data = await self._execute_query(
                query=STOP_TRANSACTION_MUTATION,
                variables={
                    "chargeStationId": self._charge_station_id,
                    "channelId": self._channel_id,
                },
                operation_name="StopTransaction",
            )
            result = data.get("stopTransaction", False)
            _LOGGER.debug("Stop transaction result: %s", result)
            return result
        except FiftyFiveApiError as err:
            _LOGGER.error("Failed to stop transaction: %s", err)
            return False

    async def get_realtime_data(self) -> dict[str, Any]:
        """Get realtime charger data (without charging history)."""
        _LOGGER.debug("Fetching realtime charger data...")
        overview = await self.get_charge_station_overview()
        channel = await self.get_charge_station_channel()
        active_transaction = await self.get_active_transaction()
        active_reservation = await self.get_active_reservation()
        charge_cards = await self.get_charge_cards()

        result = {
            "overview": overview,
            "channel": channel,
            "active_transaction": active_transaction,
            "active_reservation": active_reservation,
            "charge_station_id": self._charge_station_id,
            "channel_id": self._channel_id,
            "customer_id": self._customer_id,
            "charge_cards": charge_cards,
        }
        _LOGGER.debug("Realtime data fetch complete. Summary: overview=%s, channel_status=%s, has_transaction=%s, has_reservation=%s, cards=%d",
            bool(overview),
            channel.get("globalStatus") if channel else None,
            active_transaction is not None,
            active_reservation is not None,
            len(charge_cards),
        )
        return result

    async def get_all_data(self) -> dict[str, Any]:
        """Get all charger data including charging history."""
        _LOGGER.debug("Fetching all charger data...")
        data = await self.get_realtime_data()
        charging_history = await self.get_charging_history()
        data["charging_history"] = charging_history
        _LOGGER.debug("All data fetch complete. History count: %d", len(charging_history))
        return data

    async def test_connection(self) -> bool:
        """Test the connection to the API."""
        _LOGGER.debug("Testing connection to 50Five API...")
        try:
            await self.authenticate()
            # Only test overview if we have a charge station configured
            if self._charge_station_id:
                await self.get_charge_station_overview()
            _LOGGER.debug("Connection test successful")
            return True
        except FiftyFiveApiError as err:
            _LOGGER.debug("Connection test failed: %s", err)
            return False

