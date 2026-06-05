#!/bin/bash
# Setup script for Emporia Vue Collector
# Generates .env and Mosquitto password file

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

# Generate MQTT credentials
mqtt_username="emporia"
mqtt_password=$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)

echo
echo "Generated MQTT credentials:"
echo "  Username: ${mqtt_username}"
echo "  Password: ${mqtt_password}"
echo

# Write .env
cat > .env << EOF
# Emporia credentials
EMPORIA_EMAIL=${emporia_email}
EMPORIA_PASSWORD=${emporia_password}

# MQTT broker credentials
MQTT_USERNAME=${mqtt_username}
MQTT_PASSWORD=${mqtt_password}

# Collector settings
POLL_INTERVAL=60
LOG_LEVEL=INFO
EOF

chmod 600 .env
echo "Created .env (mode 600)"

# Generate Mosquitto password file using the mosquitto container
echo "Generating Mosquitto password file..."
docker run --rm \
    -v "$(pwd)/mosquitto:/mosquitto/config" \
    eclipse-mosquitto:2 \
    mosquitto_passwd -b -c /mosquitto/config/passwords "${mqtt_username}" "${mqtt_password}"

chmod 600 mosquitto/passwords
echo "Created mosquitto/passwords (mode 600)"

echo
echo "=== Setup complete ==="
echo
echo "Next steps:"
echo "  1. Start the stack:  docker compose up -d"
echo "  2. Check logs:       docker compose logs -f collector"
echo "  3. Add MQTT to HA:"
echo "     - Go to Settings > Devices & Services > Add Integration > MQTT"
echo "     - Broker: $(ipconfig getifaddr en0 2>/dev/null || echo 'your-mac-ip')"
echo "     - Port: 1883"
echo "     - Username: ${mqtt_username}"
echo "     - Password: ${mqtt_password}"
echo
echo "The collector will auto-create energy sensors in HA via MQTT Discovery."
