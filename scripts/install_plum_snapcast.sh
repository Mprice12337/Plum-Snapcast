#!/bin/bash

set -e

echo "Installing Plum Snapcast on Raspberry Pi..."

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "Installing Docker Compose..."
    sudo apt-get update
    sudo apt-get install -y docker-compose-plugin
fi

# Clone or update the project
PROJECT_DIR="$HOME/plum-snapcast"
if [ -d "$PROJECT_DIR" ]; then
    echo "Updating existing installation..."
    cd "$PROJECT_DIR"
    git pull
else
    echo "Cloning project..."
    git clone <your-repo-url> "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi

# Start the services
echo "Starting services..."
cd docker
docker-compose up -d

echo "Installation complete!"
echo "Access the web interface at: http://$(hostname -I | awk '{print $1}'):3000"
echo "Snapcast server is running on port 1704/1705"
