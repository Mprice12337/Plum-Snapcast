#!/bin/bash

set -e

# Configuration - Update these with your Docker Hub details
DOCKER_USERNAME="${DOCKER_USERNAME:-your-dockerhub-username}"
BACKEND_IMAGE_NAME="plum-snapcast-server"
FRONTEND_IMAGE_NAME="plum-snapcast-frontend"
TAG="${TAG:-latest}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[BUILD]${NC} $1"
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is installed and running
if ! command -v docker &> /dev/null; then
    error "Docker is not installed"
    exit 1
fi

if ! docker info &> /dev/null; then
    error "Docker is not running"
    exit 1
fi

# Check if buildx is available
if ! docker buildx version &> /dev/null; then
    error "Docker buildx is not available. Please install Docker Desktop or enable buildx"
    exit 1
fi

# Check if user is logged into Docker Hub
if ! docker info 2>/dev/null | grep -q "Username:"; then
    warn "You may need to login to Docker Hub first:"
    echo "docker login"
fi

# Validate Docker username
if [ "$DOCKER_USERNAME" = "your-dockerhub-username" ]; then
    error "Please set your Docker Hub username:"
    echo "export DOCKER_USERNAME=your-actual-username"
    echo "Then run this script again"
    exit 1
fi

info "Building images for Docker Hub account: $DOCKER_USERNAME"
info "Backend image: $DOCKER_USERNAME/$BACKEND_IMAGE_NAME:$TAG"
info "Frontend image: $DOCKER_USERNAME/$FRONTEND_IMAGE_NAME:$TAG"

# Create and use buildx builder if it doesn't exist
BUILDER_NAME="plum-snapcast-builder"
if ! docker buildx ls | grep -q "$BUILDER_NAME"; then
    log "Creating new buildx builder: $BUILDER_NAME"
    docker buildx create --name "$BUILDER_NAME" --driver docker-container --use
else
    log "Using existing buildx builder: $BUILDER_NAME"
    docker buildx use "$BUILDER_NAME"
fi

# Ensure builder is running
log "Starting buildx builder..."
docker buildx inspect --bootstrap

# Navigate to project root
cd "$(dirname "$0")/.."

# Build backend (snapcast server) for multiple architectures
log "Building backend image for linux/amd64 and linux/arm64..."
log "This will take several minutes as it compiles Rust code and other components..."

docker buildx build \
    --platform linux/amd64,linux/arm64 \
    --file backend/Dockerfile \
    --tag "$DOCKER_USERNAME/$BACKEND_IMAGE_NAME:$TAG" \
    --push \
    --progress=plain \
    backend/

log "✅ Backend build complete: $DOCKER_USERNAME/$BACKEND_IMAGE_NAME:$TAG"

# Build frontend for multiple architectures
log "Building frontend image for linux/amd64 and linux/arm64..."

docker buildx build \
    --platform linux/amd64,linux/arm64 \
    --file frontend/Dockerfile \
    --tag "$DOCKER_USERNAME/$FRONTEND_IMAGE_NAME:$TAG" \
    --build-arg VITE_SNAPCAST_HOST=plum-snapcast-server \
    --build-arg VITE_SNAPCAST_PORT=1704 \
    --build-arg VITE_SNAPCAST_WEB_PORT=1780 \
    --push \
    --progress=plain \
    frontend/

log "✅ Frontend build complete: $DOCKER_USERNAME/$FRONTEND_IMAGE_NAME:$TAG"

echo ""
log "🎉 All images pushed to Docker Hub successfully!"
info "Backend: $DOCKER_USERNAME/$BACKEND_IMAGE_NAME:$TAG"
info "Frontend: $DOCKER_USERNAME/$FRONTEND_IMAGE_NAME:$TAG"

echo ""
log "Next steps:"
echo "1. On your Raspberry Pi, update docker/.env with:"
echo "   DOCKER_USERNAME=$DOCKER_USERNAME"
echo "   TAG=$TAG"
echo ""
echo "2. Then run:"
echo "   cd docker && docker-compose pull && docker-compose up -d"