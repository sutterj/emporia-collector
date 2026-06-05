# Emporia Vue Energy Collector

A self-contained Docker service that polls the Emporia Vue cloud API and publishes energy data to MQTT for Home Assistant consumption.

## Why?

The existing `ha-emporia-vue` HACS integration runs third-party code (`PyEmVue`, `pycognito`) directly inside Home Assistant.  This collector isolates the untrusted cloud interaction in a separate container with no access to HA's API, devices, or configuration.

## Security Design

- **Minimal dependencies:** Only `paho-mqtt` (Eclipse Foundation).  Auth and HTTP use Python stdlib only.
- **No access to HA:** The collector publishes to MQTT; HA consumes sensors.  The collector never touches HA's API.
- **Container hardening:** Runs as non-root, read-only filesystem, all capabilities dropped, no-new-privileges.
- **MQTT authentication:** Connects to HA's Mosquitto add-on with a dedicated user account.
- **Credentials isolated:** Emporia credentials live only in the collector container's environment.  HA never sees them.

## Architecture

```
Emporia Cloud API  <---->  Collector (Docker)  ---->  HA Mosquitto Add-on  <---->  Home Assistant
                           (polls every 60s)         (port 1883)                  (MQTT integration)
```

## Quick Start

```bash
# 1. Install HA Mosquitto add-on
#    Settings > Add-ons > Add-on Store > Mosquitto broker > Install > Start

# 2. Create an MQTT user in HA
#    Settings > People > Users > Add User (e.g., "emporia")

# 3. Clone/navigate to this directory
cd ~/Code/emporia-collector

# 4. Run setup (enter Emporia creds + MQTT user/pass from step 2)
chmod +x setup.sh
./setup.sh

# 5. Start the collector
docker compose up -d

# 6. Check logs
docker compose logs -f collector
```

Sensors auto-appear in HA via MQTT Discovery under "Emporia Vue - [device name]".

## Configuration

All configuration is via environment variables in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `EMPORIA_EMAIL` | (required) | Your Emporia account email |
| `EMPORIA_PASSWORD` | (required) | Your Emporia account password |
| `MQTT_USERNAME` | (required) | MQTT broker username |
| `MQTT_PASSWORD` | (required) | MQTT broker password |
| `POLL_INTERVAL` | `60` | Seconds between API polls |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

## What Gets Published

The collector creates one HA sensor entity per circuit on your Vue.  For a Vue Gen 3 with 16 circuits, you'll get sensors like:

- `sensor.emporia_vue_<gid>_main` (whole-home watts)
- `sensor.emporia_vue_<gid>_circuit_1` through `circuit_16`
- `sensor.emporia_vue_<gid>_balance` (unmeasured remainder)

Each sensor reports:
- Power in watts (device_class: power, state_class: measurement)
- Availability tied to collector status

## Testing Auth

Before starting the full stack, you can verify your Emporia credentials work:

```bash
# Build the collector image
docker compose build collector

# Run auth test (one-shot, exits after successful auth)
docker compose run --rm collector python test_auth.py
```

## Running Tests

```bash
# Run the full test suite with coverage
docker compose --profile test run --rm test

# Or build and run manually
docker build -f collector/Dockerfile.test -t emporia-test ./collector
docker run --rm emporia-test
```

Tests use mocks and don't require network access or real credentials.

## Stopping

```bash
docker compose down
```

## Files

```
emporia-collector/
├── docker-compose.yml      # Collector service definition
├── setup.sh                # Interactive setup script
├── .env                    # Credentials (git-ignored, mode 600)
├── .env.example            # Template
├── .gitignore
├── README.md
├── collector/
│   ├── Dockerfile
│   ├── Dockerfile.test     # Test runner image
│   ├── pyproject.toml      # pytest + coverage config
│   ├── requirements.txt    # Only paho-mqtt
│   ├── requirements-dev.txt # + pytest, pytest-cov
│   ├── main.py             # Entry point, polling loop
│   ├── cognito_srp.py      # AWS Cognito SRP auth (stdlib only)
│   ├── emporia_api.py      # Emporia REST API client (urllib only)
│   ├── mqtt_publisher.py   # MQTT + HA Discovery
│   ├── test_auth.py        # One-shot auth verification (live)
│   └── tests/
│       ├── test_cognito_srp.py
│       ├── test_emporia_api.py
│       ├── test_mqtt_publisher.py
│       └── test_main.py
└── mosquitto/              # Legacy (not used, kept for reference)
    └── mosquitto.conf
```

## Acknowledgments

This project is inspired by [magico13/ha-emporia-vue](https://github.com/magico13/ha-emporia-vue) and its [PyEmVue](https://github.com/magico13/PyEmVue) library.  The Cognito SRP authentication logic is modeled on [NabuCasa/pycognito](https://github.com/NabuCasa/pycognito).  Both were reimplemented from scratch using only Python stdlib to eliminate external dependency risk.
