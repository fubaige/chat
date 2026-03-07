#!/bin/bash
# Neo4j Remote Access Configuration Script (V2 - Auto-Find)
# Run this on your Linux Neo4j server with root privileges (sudo)

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (sudo ./setup_neo4j_linux.sh)"
  exit 1
fi

echo "==========================================="
echo "   Neo4j Remote Configuration Helper (V2)"
echo "==========================================="

# 1. Locate neo4j.conf
echo "[1/4] Locating neo4j.conf..."
CONF_FILE=""

# Common locations
LOCATIONS=(
  "/etc/neo4j/neo4j.conf"
  "/var/lib/neo4j/conf/neo4j.conf"
  "/usr/local/neo4j/conf/neo4j.conf"
  "$HOME/neo4j/conf/neo4j.conf"
)

# Check Conda env if available
if command -v conda >/dev/null 2>&1; then
  CONDA_PATH="$(conda info --base 2>/dev/null)"
  if [ -n "$CONDA_PATH" ]; then
    LOCATIONS+=("$CONDA_PATH/etc/neo4j/neo4j.conf")
    # Check current active env
    if [ -n "$CONDA_PREFIX" ]; then
       LOCATIONS+=("$CONDA_PREFIX/etc/neo4j/neo4j.conf")
    fi
  fi
fi

for LOC in "${LOCATIONS[@]}"; do
  if [ -f "$LOC" ]; then
    CONF_FILE="$LOC"
    break
  fi
done

# If still not found, try a broader search using find
if [ -z "$CONF_FILE" ]; then
  echo "Standard locations check failed. Searching in common directories (this may take a moment)..."
  # Search in /etc, /usr, /var, /opt, /home, /root
  FOUND=$(find / -name "neo4j.conf" -type f 2>/dev/null | head -n 1)
  if [ -n "$FOUND" ]; then
    CONF_FILE="$FOUND"
  fi
fi

if [ -z "$CONF_FILE" ]; then
  echo "Error: neo4j.conf could not be found automatically."
  echo "Please input the full path to neo4j.conf:"
  read -r CONF_FILE
  if [ ! -f "$CONF_FILE" ]; then
    echo "File not found! Exiting."
    exit 1
  fi
fi

echo "Found config at: $CONF_FILE"

# 2. Backup and Modify Config
echo "[2/4] Modifying Configuration..."
cp "$CONF_FILE" "${CONF_FILE}.bak_$(date +%F_%H%M%S)"
echo "Backup created at ${CONF_FILE}.bak_$(date +%F_%H%M%S)"

# Uncomment/Set default_listen_address to 0.0.0.0
if grep -q "dbms.default_listen_address" "$CONF_FILE"; then
  # Check if commented out
  sed -i 's/^#*dbms.default_listen_address=.*/dbms.default_listen_address=0.0.0.0/' "$CONF_FILE"
else
  echo "" >> "$CONF_FILE"
  echo "# Allow remote connections" >> "$CONF_FILE"
  echo "dbms.default_listen_address=0.0.0.0" >> "$CONF_FILE"
fi

# Uncomment/Set bolt connector
if grep -q "dbms.connector.bolt.listen_address" "$CONF_FILE"; then
  sed -i 's/^#*dbms.connector.bolt.listen_address=.*/dbms.connector.bolt.listen_address=:7688/' "$CONF_FILE"
else
  # Add block if missing
  echo "" >> "$CONF_FILE"
  echo "dbms.connector.bolt.enabled=true" >> "$CONF_FILE"
  echo "dbms.connector.bolt.listen_address=:7688" >> "$CONF_FILE"
fi

echo "Config updated to allow remote connections (0.0.0.0:7688)"

# 3. Configure Firewall
echo "[3/4] Configuring Firewall..."
PORT_OPENED=false
# Detect firewall tool
if command -v ufw >/dev/null; then
  echo "Using UFW..."
  ufw allow 7688/tcp
  ufw allow 7475/tcp
  ufw reload && PORT_OPENED=true
elif command -v firewall-cmd >/dev/null; then
  echo "Using FirewallD..."
  firewall-cmd --zone=public --add-port=7688/tcp --permanent
  firewall-cmd --zone=public --add-port=7475/tcp --permanent
  firewall-cmd --reload && PORT_OPENED=true
elif command -v iptables >/dev/null; then
  echo "Using IPTables..."
  iptables -A INPUT -p tcp --dport 7688 -j ACCEPT
  iptables -A INPUT -p tcp --dport 7475 -j ACCEPT
  PORT_OPENED=true
else
  echo "Warning: No known firewall tool found (ufw/firewalld/iptables). Please open ports 7688/7475 manually."
fi

if [ "$PORT_OPENED" = true ]; then
    echo "Firewall configured successfully."
fi

# 4. Restart Neo4j
echo "[4/4] Restarting Neo4j Service..."
if systemctl list-unit-files | grep -q neo4j; then
  if systemctl is-active --quiet neo4j; then
    systemctl restart neo4j
    echo "Neo4j service restarted via systemctl."
  else
    # Try to start
    systemctl start neo4j
    echo "Neo4j service started via systemctl."
  fi
else
    # If not a systemd service (e.g. tarball run), try to find 'neo4j' executable in bin parallel to conf
    BIN_DIR="$(dirname "$(dirname "$CONF_FILE")")/bin"
    if [ -f "$BIN_DIR/neo4j" ]; then
        echo "Restarting via binary: $BIN_DIR/neo4j"
        "$BIN_DIR/neo4j" restart || "$BIN_DIR/neo4j" start
    else
        echo "Warning: Neo4j does not seem to be running as a systemd service and binary not found relative to config."
        echo "Please restart Neo4j manually for changes to take effect."
    fi
fi

echo "==========================================="
echo "   Configuration Complete!"
echo "   You can now connect to Neo4j via: bolt://<YOUR_SERVER_IP>:7688"
echo "==========================================="
