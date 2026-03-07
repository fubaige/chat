#!/bin/bash
# Neo4j 4.4 + APOC Installation Script
# Run with sudo

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (sudo ./install_apoc_linux.sh)"
  exit 1
fi

echo "==========================================="
echo "   Neo4j APOC Plugin Installer (for 4.4)"
echo "==========================================="

# 1. Locate Plugins Directory and Config
PLUGINS_DIR="/var/lib/neo4j/plugins"
CONF_FILE="/etc/neo4j/neo4j.conf"

# Try to find directories if standard ones don't exist
if [ ! -d "$PLUGINS_DIR" ]; then
    echo "Standard plugins dir not found. Searching..."
    FOUND_DIR=$(find / -name "plugins" -type d 2>/dev/null | grep "neo4j" | head -n 1)
    if [ -n "$FOUND_DIR" ]; then
        PLUGINS_DIR="$FOUND_DIR"
    else
        echo "Error: Could not find Neo4j plugins directory."
        exit 1
    fi
fi

if [ ! -f "$CONF_FILE" ]; then
    echo "Standard config not found. Searching..."
    FOUND_CONF=$(find / -name "neo4j.conf" -type f 2>/dev/null | head -n 1)
    if [ -n "$FOUND_CONF" ]; then
        CONF_FILE="$FOUND_CONF"
    else
        echo "Error: Could not find neo4j.conf."
        exit 1
    fi
fi

echo "Plugins Dir: $PLUGINS_DIR"
echo "Config File: $CONF_FILE"

# 2. Download APOC Jar
echo "[1/3] Downloading APOC for Neo4j 4.4..."
APOC_URL="https://github.com/neo4j-contrib/neo4j-apoc-procedures/releases/download/4.4.0.30/apoc-4.4.0.30-all.jar"
APOC_JAR="$PLUGINS_DIR/apoc-4.4.0.30-all.jar"

# Remove old apoc jars
rm -f "$PLUGINS_DIR"/apoc-*.jar

# Download
if command -v wget >/dev/null; then
    wget -q --show-progress -O "$APOC_JAR" "$APOC_URL"
elif command -v curl >/dev/null; then
    curl -L -o "$APOC_JAR" "$APOC_URL"
else
    echo "Error: Neither wget nor curl found. Cannot download APOC."
    exit 1
fi

if [ -f "$APOC_JAR" ]; then
    echo "APOC downloaded successfully."
    chmod 644 "$APOC_JAR"
    chown neo4j:neo4j "$APOC_JAR" 2>/dev/null || echo "Warning: Could not chown to neo4j user."
else
    echo "Error: Download failed."
    exit 1
fi

# 3. Configure neo4j.conf
echo "[2/3] Configuring neo4j.conf..."
cp "$CONF_FILE" "${CONF_FILE}.bak_apoc_$(date +%F_%H%M%S)"

# Helper function to append or replace
configure_setting() {
    local key=$1
    local value=$2
    local file=$3
    
    if grep -q "^[#]*$key" "$file"; then
        # Replace existing line (commented or not)
        sed -i "s|^[#]*$key.*|$key=$value|" "$file"
    else
        # Append if not found
        echo "$key=$value" >> "$file"
    fi
}

configure_setting "dbms.security.procedures.unrestricted" "apoc.*" "$CONF_FILE"
configure_setting "dbms.security.procedures.allowlist" "apoc.*" "$CONF_FILE"

echo "Config updated to allow APOC."

# 4. Restart Neo4j
echo "[3/3] Restarting Neo4j..."
if systemctl list-unit-files | grep -q neo4j; then
    systemctl restart neo4j
else
    # Try binary restart
    BIN_DIR="$(dirname "$(dirname "$CONF_FILE")")/bin"
    "$BIN_DIR/neo4j" restart
fi

echo "==========================================="
echo "   APOC Installation Complete!"
echo "   Please wait 30s for Neo4j to fully start."
echo "==========================================="
