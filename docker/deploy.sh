#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Plum Snapcast Deployment ===${NC}"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo -e "${YELLOW}Creating .env from .env.example${NC}"
        cp .env.example .env
        echo -e "${RED}Please edit .env file and set your DOCKER_USERNAME${NC}"
        exit 1
    else
        echo -e "${RED}Error: .env.example not found${NC}"
        exit 1
    fi
fi

# Load environment variables
source .env

# Check if DOCKER_USERNAME is set
if [ -z "$DOCKER_USERNAME" ]; then
    echo -e "${RED}Error: DOCKER_USERNAME not set in .env file${NC}"
    exit 1
fi

# Pull latest images
echo -e "${YELLOW}Pulling latest images from Docker Hub...${NC}"
docker-compose pull

# Stop existing containers
echo -e "${YELLOW}Stopping existing containers...${NC}"
docker-compose down

# Start containers
echo -e "${YELLOW}Starting containers...${NC}"
docker-compose up -d

# Wait for services to be healthy
echo -e "${YELLOW}Waiting for services to be healthy...${NC}"
sleep 90

# Check status
echo ""
echo -e "${GREEN}=== Container Status ===${NC}"
docker-compose ps

# Check logs
echo ""
echo -e "${GREEN}=== Recent Logs ===${NC}"
docker-compose logs --tail=20

echo ""
echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo ""
echo "Services:"
echo "  - Snapcast Server: http://localhost:1780 (WebUI)"
echo "  - Snapcast Frontend: http://localhost:${FRONTEND_PORT:-3000}"
echo "  - AirPlay Device: ${AIRPLAY_DEVICE_NAME:-Plum Audio}"
echo ""
echo "To view logs:"
echo "  docker-compose logs -f"
echo ""
echo "To restart services:"
echo "  docker-compose restart"
