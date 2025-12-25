#!/bin/bash
# Pycore Installation Script
echo "================================================"
echo "         Pycore Installation Script            "
echo "           Powered by Pycore Cloud Team        "
echo "================================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

# Update system
echo "[1/7] Updating system packages..."
apt update && apt upgrade -y

# Install LXC/LXD
echo "[2/7] Installing LXC and dependencies..."
apt install lxc lxc-utils bridge-utils uidmap -y

echo "[3/7] Installing snapd..."
apt install snapd -y
systemctl enable --now snapd.socket

echo "[4/7] Installing LXD..."
snap install lxd
# Add user to lxd group
if [ -n "$SUDO_USER" ]; then
    usermod -aG lxd $SUDO_USER
    echo "Added $SUDO_USER to lxd group"
else
    echo "Warning: Could not detect sudo user. Please add your user to lxd group manually:"
    echo "sudo usermod -aG lxd \$USER"
fi


# Install Python and pip
echo "[5/7] Installing Python and pip..."
apt install python3 python3-pip python3-venv pythonpy -y

# Create virtual environment
echo "[6/7] Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
echo "[7/7] Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

# Create data directories
mkdir -p data
mkdir -p static/uploads/{logos,backgrounds,payments}
sudo lxd init
newgrp lxd
# Set permissions
chown -R $SUDO_USER:$SUDO_USER .

echo ""
echo "================================================"
echo "         Installation Complete!                 "
echo "================================================"
