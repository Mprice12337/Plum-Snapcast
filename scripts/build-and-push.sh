#!/bin/bash

set -e

# Configuration - Can be overridden with environment variables
DOCKER_USERNAME="${DOCKER_USERNAME:-your-dockerhub-username}"
BACKEND_IMAGE_NAME="plum-snapcast-server"
FRONTEND_IMAGE_NAME="plum-snapcast-frontend"
TAG="${TAG:-latest}"

# Build options
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
NO_CACHE="${NO_CACHE:-false}"
PUSH="${PUSH:-true}"

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

# Print usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Build and push Docker images for Plum-Snapcast"
    echo ""
    echo "Options:"
    echo "  -u, --username USERNAME    Docker Hub username (required)"
    echo "  -t, --tag TAG              Image tag (default: latest)"
    echo "  -p, --platforms PLATFORMS  Build platforms (default: linux/amd64,linux/arm64)"
    echo "  --no-cache                 Build without cache"
    echo "  --no-push                  Build only, don't push to Docker Hub"
    echo "  --backend-only             Build only backend image"
    echo "  --frontend-only            Build only frontend image"
    echo "  -h, --help                 Show this help message"
    echo ""
    echo "Environment variables:"
    echo "  DOCKER_USERNAME            Docker Hub username"
    echo "  TAG                        Image tag"
    echo "  PLATFORMS                  Build platforms"
    echo ""
    echo "Examples:"
    echo "  $0 -u myusername                          # Build and push both images"
    echo "  $0 -u myusername --backend-only           # Build backend only"
    echo "  $0 -u myusername --no-cache               # Build without cache"
    echo "  $0 -u myusername --no-push                # Build locally without pushing"
    echo "  DOCKER_USERNAME=myuser TAG=v1.0 $0        # Use env variables"
    exit 0
}

# Parse command line arguments
BUILD_BACKEND=true
BUILD_FRONTEND=true

while [[ $# -gt 0 ]]; do
    case $1 in
        -u|--username)
            DOCKER_USERNAME="$2"
            shift 2
            ;;
        -t|--tag)
            TAG="$2"
            shift 2
            ;;
        -p|--platforms)
            PLATFORMS="$2"
            shift 2
            ;;
        --no-cache)
            NO_CACHE=true
            shift
            ;;
        --no-push)
            PUSH=false
            shift
            ;;
        --backend-only)
            BUILD_FRONTEND=false
            shift
            ;;
        --frontend-only)
            BUILD_BACKEND=false
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            error "Unknown option: $1"
            usage
            ;;
    esac
done

# Validate Docker username
if [ "$DOCKER_USERNAME" = "your-dockerhub-username" ] || [ -z "$DOCKER_USERNAME" ]; then
    error "Please set your Docker Hub username:"
    echo ""
    echo "  Option 1: Use environment variable"
    echo "    export DOCKER_USERNAME=your-actual-username"
    echo "    $0"
    echo ""
    echo "  Option 2: Use command line argument"
    echo "    $0 --username your-actual-username"
    echo ""
    exit 1
fi

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

# Check if user is logged into Docker Hub (only if pushing)
if [ "$PUSH" = true ]; then
    if ! docker info 2>/dev/null | grep -q "Username:"; then
        warn "You may need to login to Docker Hub first:"
        echo "  docker login"
        echo ""
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
fi

# Print build configuration
echo ""
info "Build Configuration:"
info "  Docker Username: $DOCKER_USERNAME"
info "  Tag: $TAG"
info "  Platforms: $PLATFORMS"
info "  No Cache: $NO_CACHE"
info "  Push to Hub: $PUSH"
info "  Backend Image: $DOCKER_USERNAME/$BACKEND_IMAGE_NAME:$TAG"
info "  Frontend Image: $DOCKER_USERNAME/$FRONTEND_IMAGE_NAME:$TAG"
echo ""

if [ "$BUILD_BACKEND" = false ] && [ "$BUILD_FRONTEND" = false ]; then
    error "Cannot use --backend-only and --frontend-only together"
    exit 1
fi

# Create and use buildx builder if it doesn't exist
BUILDER_NAME="plum-snapcast-builder"
if ! docker buildx ls | grep -q "$BUILDER_NAME"; then
    log "Creating new buildx builder: $BUILDER_NAME"
    docker buildx create --name "$BUILDER_NAME" --driver docker-container --bootstrap --use
else
    log "Using existing buildx builder: $BUILDER_NAME"
    docker buildx use "$BUILDER_NAME"
fi

# Ensure builder is running
log "Bootstrapping buildx builder..."
docker buildx inspect --bootstrap

# Navigate to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Build cache arguments
CACHE_ARGS=""
if [ "$NO_CACHE" = true ]; then
    CACHE_ARGS="--no-cache"
fi

# Push arguments
PUSH_ARGS=""
if [ "$PUSH" = true ]; then
    PUSH_ARGS="--push"
else
    PUSH_ARGS="--load"
    # When loading locally, can only build for current platform
    CURRENT_PLATFORM=$(docker version --format '{{.Server.Os}}/{{.Server.Arch}}')
    warn "Building for local use only, limiting to current platform: $CURRENT_PLATFORM"
    PLATFORMS="$CURRENT_PLATFORM"
fi

# Build backend image
if [ "$BUILD_BACKEND" = true ]; then
    log "Building backend image..."
    warn "This will take 10-15 minutes as it compiles shairport-sync and librespot from source..."
    echo ""

    START_TIME=$(date +%s)

    docker buildx build \
        --platform "$PLATFORMS" \
        --file backend/Dockerfile \
        --tag "$DOCKER_USERNAME/$BACKEND_IMAGE_NAME:$TAG" \
        $PUSH_ARGS \
        $CACHE_ARGS \
        --progress=plain \
        backend/ 2>&1 | tee /tmp/backend-build.log | grep -E "^\[|=>|DONE|ERROR|WARN" || true

    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    if [ ${PIPESTATUS[0]} -eq 0 ]; then
        log "✅ Backend build complete in ${DURATION}s: $DOCKER_USERNAME/$BACKEND_IMAGE_NAME:$TAG"
    else
        error "Backend build failed! Check /tmp/backend-build.log for details"
        exit 1
    fi
    echo ""
fi

# Build frontend image
if [ "$BUILD_FRONTEND" = true ]; then
    log "Building frontend image..."
    echo ""

    START_TIME=$(date +%s)

    docker buildx build \
        --platform "$PLATFORMS" \
        --file frontend/Dockerfile \
        --tag "$DOCKER_USERNAME/$FRONTEND_IMAGE_NAME:$TAG" \
        --build-arg VITE_SNAPCAST_HOST=localhost \
        --build-arg VITE_SNAPCAST_PORT=1704 \
        --build-arg VITE_SNAPCAST_WEB_PORT=1780 \
        $PUSH_ARGS \
        $CACHE_ARGS \
        --progress=plain \
        frontend/ 2>&1 | tee /tmp/frontend-build.log | grep -E "^\[|=>|DONE|ERROR|WARN" || true

    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    if [ ${PIPESTATUS[0]} -eq 0 ]; then
        log "✅ Frontend build complete in ${DURATION}s: $DOCKER_USERNAME/$FRONTEND_IMAGE_NAME:$TAG"
    else
        error "Frontend build failed! Check /tmp/frontend-build.log for details"
        exit 1
    fi
    echo ""
fi

# Summary
echo ""
log "🎉 Build completed successfully!"
echo ""

if [ "$PUSH" = true ]; then
    info "Images pushed to Docker Hub:"
    if [ "$BUILD_BACKEND" = true ]; then
        echo "  ✅ $DOCKER_USERNAME/$BACKEND_IMAGE_NAME:$TAG"
    fi
    if [ "$BUILD_FRONTEND" = true ]; then
        echo "  ✅ $DOCKER_USERNAME/$FRONTEND_IMAGE_NAME:$TAG"
    fi
    echo ""
    log "Next steps:"
    echo "1. On your Raspberry Pi, update docker/.env with:"
    echo "   DOCKER_USERNAME=$DOCKER_USERNAME"
    echo "   TAG=$TAG"
    echo ""
    echo "2. Then deploy:"
    echo "   cd docker"
    echo "   docker-compose pull"
    echo "   docker-compose up -d"
else
    info "Images built locally (not pushed):"
    if [ "$BUILD_BACKEND" = true ]; then
        echo "  ✅ $DOCKER_USERNAME/$BACKEND_IMAGE_NAME:$TAG"
    fi
    if [ "$BUILD_FRONTEND" = true ]; then
        echo "  ✅ $DOCKER_USERNAME/$FRONTEND_IMAGE_NAME:$TAG"
    fi
    echo ""
    info "To test locally:"
    echo "  cd backend && docker-compose up -d"
fi

echo ""
log "Build logs saved to:"
if [ "$BUILD_BACKEND" = true ]; then
    echo "  Backend: /tmp/backend-build.log"
fi
if [ "$BUILD_FRONTEND" = true ]; then
    echo "  Frontend: /tmp/frontend-build.log"
fi