#!/bin/bash
set -e

# Parse command-line arguments
NO_CACHE_FLAG=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-cache|-n)
            NO_CACHE_FLAG="--no-cache"
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Build and push multi-architecture Docker images for Plum Snapcast"
            echo ""
            echo "OPTIONS:"
            echo "  --no-cache, -n    Force rebuild without using cache (use when config files changed)"
            echo "  --help, -h        Show this help message"
            echo ""
            echo "EXAMPLES:"
            echo "  $0                # Normal build with cache"
            echo "  $0 --no-cache     # Force full rebuild (useful after changing .ini files)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Load environment variables
if [ -f .env ]; then
    source .env
else
    echo "Error: .env file not found. Copy .env.example to .env and configure it."
    exit 1
fi

# Check if DOCKER_USERNAME is set
if [ -z "$DOCKER_USERNAME" ]; then
    echo "Error: DOCKER_USERNAME not set in .env file"
    exit 1
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Plum Snapcast Multi-Architecture Build ===${NC}"
if [ -n "$NO_CACHE_FLAG" ]; then
    echo -e "${YELLOW}⚠ Building with --no-cache (ignoring Docker cache)${NC}"
fi
echo ""

# Check if buildx is available
if ! docker buildx version > /dev/null 2>&1; then
    echo -e "${RED}Error: docker buildx is not available${NC}"
    echo "Please install Docker Buildx or use Docker Desktop which includes it"
    exit 1
fi

# Create or use existing buildx builder
BUILDER_NAME="plum-snapcast-builder"
if ! docker buildx inspect $BUILDER_NAME > /dev/null 2>&1; then
    echo -e "${YELLOW}Creating new buildx builder: $BUILDER_NAME${NC}"
    docker buildx create --name $BUILDER_NAME --use --bootstrap
else
    echo -e "${YELLOW}Using existing buildx builder: $BUILDER_NAME${NC}"
    docker buildx use $BUILDER_NAME
fi

# Login to Docker Hub
echo -e "${YELLOW}Logging in to Docker Hub...${NC}"
docker login

# Build and push backend
echo ""
echo -e "${GREEN}=== Building Backend (Snapcast Server) ===${NC}"
echo -e "${YELLOW}Platforms: linux/amd64, linux/arm64${NC}"
docker buildx build \
    $NO_CACHE_FLAG \
    --platform linux/amd64,linux/arm64 \
    --tag $DOCKER_USERNAME/plum-snapcast-server:latest \
    --tag $DOCKER_USERNAME/plum-snapcast-server:$(date +%Y%m%d) \
    --push \
    ../backend

echo -e "${GREEN}✓ Backend build and push complete${NC}"

# Build and push frontend
echo ""
echo -e "${GREEN}=== Building Frontend ===${NC}"
echo -e "${YELLOW}Platforms: linux/amd64, linux/arm64${NC}"
docker buildx build \
    $NO_CACHE_FLAG \
    --platform linux/amd64,linux/arm64 \
    --tag $DOCKER_USERNAME/plum-snapcast-frontend:latest \
    --tag $DOCKER_USERNAME/plum-snapcast-frontend:$(date +%Y%m%d) \
    --push \
    ../frontend

echo -e "${GREEN}✓ Frontend build and push complete${NC}"

echo ""
echo -e "${GREEN}=== Build Complete ===${NC}"
echo ""
echo "Images pushed:"
echo "  - $DOCKER_USERNAME/plum-snapcast-server:latest"
echo "  - $DOCKER_USERNAME/plum-snapcast-server:$(date +%Y%m%d)"
echo "  - $DOCKER_USERNAME/plum-snapcast-frontend:latest"
echo "  - $DOCKER_USERNAME/plum-snapcast-frontend:$(date +%Y%m%d)"
echo ""
echo "To deploy on your Raspberry Pi, run:"
echo "  cd docker"
echo "  docker-compose pull"
echo "  docker-compose up -d"