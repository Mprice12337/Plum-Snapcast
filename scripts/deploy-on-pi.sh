#!/bin/bash

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[DEPLOY]${NC} $1"
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Navigate to docker directory
cd "$(dirname "$0")/../docker"

# Check if .env file exists
if [ ! -f .env ]; then
    warn ".env file not found. Please create it with your Docker Hub username:"
    echo ""
    echo "cd docker"
    echo "cp .env.example .env"
    echo "# Edit .env file with your Docker Hub username"
    exit 1
fi

# Source the .env file to get variables
source .env

# Validate Docker username
if [ "$DOCKER_USERNAME" = "your-dockerhub-username" ] || [ -z "$DOCKER_USERNAME" ]; then
    warn "Please update DOCKER_USERNAME in docker/.env file"
    exit 1
fi

info "Deploying images from Docker Hub account: $DOCKER_USERNAME"

# Pull latest images
log "Pulling latest images..."
docker-compose pull

# Stop existing containers
log "Stopping existing containers..."
docker-compose down

# Start services
log "Starting services..."
docker-compose up -d

# Wait a moment for services to start
sleep 5

# Show status
log "Deployment complete!"
docker-compose ps

echo ""
log "🎉 Services are running:"
PI_IP=$(hostname -I | awk '{print $1}')
info "  Frontend: http://$PI_IP:3000"
info "  Snapcast: $PI_IP:1704"
echo ""
log "Check logs with: docker-compose logs -f"