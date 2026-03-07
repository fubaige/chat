#!/bin/bash
# Neo4j 4.4 Manual Installation Script (Ubuntu/Debian & CentOS/RHEL)
# Run with sudo

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (sudo ./install_neo4j_linux.sh)"
  exit 1
fi

echo "==========================================="
echo "   Neo4j 4.4 Installer & Configurator"
echo "==========================================="

# Detect OS
if [ -f /etc/debian_version ]; then
    OS="debian"
    echo "Detected OS: Debian/Ubuntu system"
elif [ -f /etc/redhat-release ]; then
    OS="rhel"
    echo "Detected OS: RHEL/CentOS system"
else
    echo "Unsupported OS. This script supports Debian/Ubuntu or CentOS/RHEL."
    exit 1
fi

# 1. Install Java 11 (Required for Neo4j 4.x)
echo "[1/5] Installing Java 11..."
if ! java -version 2>&1 | grep -q "version \"11"; then
    if [ "$OS" == "debian" ]; then
        apt-get update
        apt-get install -y openjdk-11-jdk
    else
        yum install -y java-11-openjdk
    fi
else
    echo "Java 11 appears to be installed."
fi

# 2. Add Neo4j Repository & Install
echo "[2/5] Installing Neo4j 4.4..."
if [ "$OS" == "debian" ]; then
    # Add key
    wget -O - https://debian.neo4j.com/neotechnology.gpg.key | apt-key add -
    # Add repo
    echo 'deb https://debian.neo4j.com stable 4.4' > /etc/apt/sources.list.d/neo4j.list
    apt-get update
    apt-get install -y neo4j=1:4.4.*
else
    # CentOS/RHEL
    rpm --import https://debian.neo4j.com/neotechnology.gpg.key
    cat <<EOF > /etc/yum.repos.d/neo4j.repo
[neo4j]
name=Neo4j RPM Repository
baseurl=https://yum.neo4j.com/stable/4.4
enabled=1
gpgcheck=1
EOF
    yum install -y neo4j-4.4.*
fi

# 3. Enable Service
echo "[3/5] Enabling Neo4j Service..."
systemctl enable neo4j

# 4. Set Initial Password & Config
echo "[4/5] Configuring Neo4j..."
# Reset password using neo4j-admin (must be done while service is stopped or using specific tool)
# For a fresh install, auth is enabled. We will set it via specific command or wait for user.
# Actually, let's configure config FIRST to allow connections.

CONF_FILE="/etc/neo4j/neo4j.conf"
if [ -f "$CONF_FILE" ]; then
    # Allow remote connections
    sed -i 's/^#*dbms.default_listen_address=.*/dbms.default_listen_address=0.0.0.0/' "$CONF_FILE"
    sed -i 's/^#*dbms.connector.bolt.listen_address=.*/dbms.connector.bolt.listen_address=:7687/' "$CONF_FILE"
    echo "Configuration updated for remote access."
else
    echo "Warning: neo4j.conf not found at expected /etc/neo4j/neo4j.conf"
fi

# Firewall
if command -v ufw >/dev/null; then
    ufw allow 7687/tcp
    ufw allow 7474/tcp
elif command -v firewall-cmd >/dev/null; then
    firewall-cmd --zone=public --add-port=7687/tcp --permanent
    firewall-cmd --zone=public --add-port=7474/tcp --permanent
    firewall-cmd --reload
fi

# 5. Start Service
echo "[5/5] Starting Neo4j..."
systemctl restart neo4j

echo "Waiting for Neo4j to start (15s)..."
sleep 15

# Set password using cypher-shell (User: neo4j, Default Pass: neo4j)
echo "Setting password to '12345678'..."
# Try to change default password 'neo4j' to '12345678'
echo "CALL dbms.security.changePassword('12345678');" | cypher-shell -u neo4j -p neo4j 2>/dev/null

if [ $? -eq 0 ]; then
    echo "Password changed successfully."
else
    echo "Note: Password change might have failed or already been changed."
    echo "If this is a fresh install, default is 'neo4j'/'neo4j'. Please change it manually if needed."
fi

echo "==========================================="
echo "   Installation Complete!"
echo "   Connection: bolt://<YOUR_IP>:7687"
echo "   User: neo4j"
echo "   Password: 12345678"
echo "==========================================="
