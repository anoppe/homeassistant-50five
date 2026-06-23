# 50Five EV Charger Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/anoppe/homeassistant-50five.svg)](https://github.com/anoppe/homeassistant-50five/releases)
[![License](https://img.shields.io/github/license/anoppe/homeassistant-50five.svg)](LICENSE)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=anoppe&repository=https%3A%2F%2Fgithub.com%2Fanoppe%2Fhomeassistant-50five&category=Integration)

This custom integration allows you to monitor and control your 50Five EV charger from Home Assistant.

## Features

- **Charger Status Monitoring**: View the current status of your charger channel
- **Access Configuration**: See authorization mode, access type, and map publication status
- **Home Charging Compensation (HCC)**: View HCC status and tariff
- **Active Transaction Monitoring**: Track energy delivered, duration, and cost during charging
- **Reservation Status**: View active reservations
- **Start Transaction**: Button to initiate a charging session

## Installation

### Manual Installation

1. Copy the `custom_components/fifty_five` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant
3. Go to **Settings** → **Devices & Services** → **Add Integration**
4. Search for "50Five EV Charger"
5. Enter your credentials and charger information

### HACS Installation

1. Open HACS in Home Assistant
2. Click on **Integrations**
3. Click the three dots in the top right corner and select **Custom repositories**
4. Add this repository URL and select **Integration** as the category
5. Click **Add**
6. Search for "50Five EV Charger" and install it
7. Restart Home Assistant
8. Configure the integration as described above

## Configuration

During setup, you'll need to provide:

| Field | Description |
|-------|-------------|
| **Email** | Your 50Five account email address |
| **Password** | Your 50Five account password |

## Example Dashboard Card

```yaml
type: entities
title: 50Five Charger
entities:
  - entity: sensor.50five_charger_channel_status
  - entity: sensor.50five_charger_authorization_mode
  - entity: sensor.50five_charger_hcc_enabled
  - entity: sensor.50five_charger_active_transaction_energy
  - entity: sensor.50five_charger_active_transaction_duration
  - entity: switch.50five_charger_charging
```

### Charging History Card

```yaml
type: entities
title: Charging History
entities:
  - entity: sensor.50five_charger_transactions_30_days
  - entity: sensor.50five_charger_total_energy_30_days
  - entity: sensor.50five_charger_total_cost_30_days
  - entity: sensor.50five_charger_last_transaction_date
  - entity: sensor.50five_charger_last_transaction_energy
  - entity: sensor.50five_charger_last_transaction_cost
```

## Automation Examples

### Start charging when car is plugged in

```yaml
automation:
  - alias: "Start charging when car is plugged in"
    trigger:
      - platform: state
        entity_id: sensor.50five_charger_channel_status
        to: "Occupied"
    condition:
      - condition: state
        entity_id: switch.50five_charger_charging
        state: "off"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.50five_charger_charging
      - service: notify.mobile_app
        data:
          message: "Car plugged in - charging started!"
```

### Notify when charging is complete

```yaml
automation:
  - alias: "Notify when charging is stopped"
    trigger:
      - platform: state
        entity_id: switch.50five_charger_charging
        from: "on"
        to: "off"
    action:
      - service: notify.mobile_app
        data:
          message: "Your car has stopped charging!"
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License.

## Disclaimer

This integration is not officially affiliated with 50Five. Use at your own risk.



