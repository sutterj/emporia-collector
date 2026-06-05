#!/bin/bash
# Setup script for Emporia Vue Collector
# Generates .env for connecting to HA's Mosquitto add-on

set -e

cd "$(dirname "$0")"

echo "=== Emporia Vue Collector Setup ==="
echo

# Check if .env already exists
if [ -f .env ]; then
    echo ".env already exists. Delete it first to re-run setup."
    exit 1
fi

# Gather Emporia credentials
read -p "Emporia email: " emporia_email
read -sp "Emporia password: " emporia_password
echo

# MQTT broker settings (HA Mosquitto add-on)
echo
echo "MQTT broker settings (from HA Mosquitto add-on):"
read -p "HA IP address (e.g. 192.168.1.100): " mqtt_host
if [ -z "$mqtt_host" ]; then
  echo "Error: HA IP address is required."
  exit 1
fi
read -p "MQTT username: " mqtt_username
read -sp "MQTT password: " mqtt_password
echo

# Write .env
cat > .env << EOF
# Emporia credentials
EMPORIA_EMAIL=${emporia_email}
EMPORIA_PASSWORD=${emporia_password}

# MQTT broker (HA Mosquitto add-on)
MQTT_HOST=${mqtt_host}
MQTT_PORT=1883
MQTT_USERNAME=${mqtt_username}
MQTT_PASSWORD=${mqtt_password}

# Collector settings
POLL_INTERVAL=60
LOG_LEVEL=INFO
EOF

chmod 600 .env
echo
echo "Created .env (mode 600)"

echo
echo "=== Setup complete ==="
echo
echo "Next steps:"
echo "  1. Ensure HA Mosquitto add-on is installed and running"
echo "  2. Create MQTT user '${mqtt_username}' in HA (Settings > People > Users)"
echo "  3. Start the collector:  docker compose up -d"
echo "  4. Check logs:           docker compose logs -f collector"
echo
echo "Sensors will auto-appear in HA via MQTT Discovery."
