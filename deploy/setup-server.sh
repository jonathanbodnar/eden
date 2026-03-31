#!/usr/bin/env bash
set -euo pipefail

echo "=== Eden Ingestion Platform — Hetzner Server Setup ==="

# Update system
apt-get update -y
apt-get upgrade -y

# Install Docker
if ! command -v docker &>/dev/null; then
    echo "Installing Docker..."
    apt-get install -y ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    echo "Docker installed."
else
    echo "Docker already installed."
fi

# Install git if missing
if ! command -v git &>/dev/null; then
    apt-get install -y git
fi

# Setup firewall
if command -v ufw &>/dev/null; then
    ufw allow 22/tcp
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow 3000/tcp
    ufw allow 8000/tcp
    ufw --force enable
    echo "Firewall configured."
fi

echo "=== Server setup complete ==="
