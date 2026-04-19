#!/usr/bin/env bash
set -euo pipefail

DEPLOY_DIR="/opt/eden"
REPO_URL="${REPO_URL:-https://github.com/jonathanbodnar/eden.git}"
BRANCH="${BRANCH:-cursor/ingestion-platform-operations-db7c}"

echo "=== Eden Ingestion Platform — Deploy ==="

# Clone or update repo
if [ -d "$DEPLOY_DIR" ]; then
    echo "Updating existing deployment..."
    cd "$DEPLOY_DIR"
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    echo "Cloning repository..."
    git clone --branch "$BRANCH" "$REPO_URL" "$DEPLOY_DIR"
    cd "$DEPLOY_DIR"
fi

# Create .env if it doesn't exist
if [ ! -f "$DEPLOY_DIR/.env" ]; then
    echo "Creating .env from template..."
    cp "$DEPLOY_DIR/.env.example" "$DEPLOY_DIR/.env"
    echo ""
    echo "WARNING: Edit /opt/eden/.env with your actual credentials before starting."
    echo ""
fi

# Build and deploy
echo "Building containers..."
docker compose build

echo "Starting services..."
docker compose up -d

echo "Waiting for services to start..."
sleep 10

# Health check
echo "Checking API health..."
for i in {1..10}; do
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        echo "API is healthy!"
        break
    fi
    echo "  Waiting... ($i/10)"
    sleep 5
done

echo ""
echo "=== Deployment complete ==="
echo "  Admin UI:  http://$(hostname -I | awk '{print $1}'):3000"
echo "  API:       http://$(hostname -I | awk '{print $1}'):8000"
echo "  API Docs:  http://$(hostname -I | awk '{print $1}'):8000/docs"
echo ""
docker compose ps
