"""Constants for the 50Five EV Charger integration."""

DOMAIN = "fifty_five"

# Configuration
CONF_CHARGE_STATION_ID = "charge_station_id"
CONF_CHANNEL_ID = "channel_id"
CONF_CUSTOMER_ID = "customer_id"

# API
API_URL = "https://lms.servicelayer.platform-01.plugz.dev/graphql"
APPLICATION_ID = "27ce6f0c-d987-4d6f-b0a3-aea459a90c1f"

# GraphQL Queries
LOGIN_MUTATION = """
mutation Login($email: String!, $password: String!) {
    login(email: $email, password: $password) {
        access_token
        expires_in
        token_type
        __typename
    }
}
"""

GET_CUSTOMER_WITH_CHARGE_STATIONS = """
query GetCustomerChargeStations {
    getCustomerChargeStations {
        ...ChargeStation
        ...ChargeStationOverview
        __typename
    }
}

fragment ChargeStation on ChargeStation {
    id
    commId
    name
    channels {
        id
        evseId
        channelNo
        globalStatus
        __typename
    }
    location {
        countryDetails {
            code
            currency {
                code
                __typename
            }
            __typename
        }
        __typename
    }
    manufacturerType {
        model
        vendor
        __typename
    }
    subscriptions {
        id
        startDate
        endDate
        product {
            id
            name
            __typename
        }
        __typename
    }
    accessOptions {
        accessType
        publishedOnMap
        __typename
    }
    chargeGroup {
        tariffVat {
            energy
            __typename
        }
        anonymousTariffVat {
            energy
            flat
            time
            __typename
        }
        __typename
    }
    __typename
}

fragment ChargeStationOverview on ChargeStation {
    id
    accessOptions {
        authorizationMode
        accessType
        publishedOnMap
        __typename
    }
    homeChargingCompensation {
        hccEnabled
        hccTariff
        __typename
    }
    __typename
}
"""

GET_CUSTOMER_CHARGE_CARDS = """
query GetCustomerChargecards($getCustomerByIdId: ID!) {
    getCustomerById(id: $getCustomerByIdId) {
        cards {
            ...Card
            __typename
        }
        __typename
    }
}

fragment Card on Card {
    id
    externalId
    roaming
    state
    type
    roamingHomeChargingEnabled
    roamingHubStatus
    cardProvider {
        name
        __typename
    }
    __typename
}
"""

GET_CHARGE_STATION_OVERVIEW = """
query GetChargeStationOverview($getChargeStationByIdId: ID!) {
    getChargeStationById(id: $getChargeStationByIdId) {
        ...ChargeStationOverview
        __typename
    }
}

fragment ChargeStationOverview on ChargeStation {
    id
    accessOptions {
        authorizationMode
        accessType
        publishedOnMap
        __typename
    }
    homeChargingCompensation {
        hccEnabled
        hccTariff
        __typename
    }
    __typename
}
"""

GET_CHARGE_STATION_CHANNEL = """
query GetChargeStationChannel($chargeStationId: ID!, $channelId: ID!) {
    getChargeStationChannel(chargeStationId: $chargeStationId, channelId: $channelId) {
        id
        globalStatus
        __typename
    }
}
"""

LMS_ACTIVE_TRANSACTION = """
query LmsActiveTransaction {
    lmsActiveTransaction {
        ...ActiveTransaction
        __typename
    }
}

fragment ActiveTransaction on Transaction {
    updateDate
    address
    zipCode
    city
    energyDelivered
    startDate
    countryCode
    currency
    totalAmount
    vat
    durationCharging
    priceElements {
        type
        price
        __typename
    }
    tariffId
    channelVisibleId
    __typename
}
"""

START_TRANSACTION_MUTATION = """
mutation StartTransaction($chargeStationId: ID!, $channelId: ID!, $card: String) {
    startTransaction(chargeStationId: $chargeStationId, channelId: $channelId, card: $card)
}
"""

STOP_TRANSACTION_MUTATION = """
mutation StopTransaction($chargeStationId: ID!, $channelId: ID!) {
    stopTransaction(chargeStationId: $chargeStationId, channelId: $channelId)
}
"""

ACTIVE_RESERVATION = """
query ActiveReservation {
    activeReservation {
        ...Reservation
        __typename
    }
}

fragment Reservation on Reservation {
    status
    start
    expiry
    appId
    id
    visualNumber
    type
    evseId
    location {
        evses {
            customEvseId
            uid
            __typename
        }
        __typename
    }
    __typename
}
"""

GET_CHARGING_HISTORY = """
query GetChargingHistory($getTransactionsFilters: TransactionFilter, $sort: TransactionSort) {
    getTransactions(filters: $getTransactionsFilters, sort: $sort) {
        hasNext
        items {
            id
            startDate
            totalDuration
            totalEnergy
            cardSnapshot {
                externalId
                __typename
            }
            locationSnapshot {
                chargeStationName
                evse {
                    id
                    __typename
                }
                __typename
            }
            transactionPrices {
                totalCost
                type
                vatPercentage
                currency {
                    code
                    __typename
                }
                vatCountry {
                    code
                    __typename
                }
                __typename
            }
            __typename
        }
        __typename
    }
}
"""
