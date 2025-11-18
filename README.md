# Plum-Snapcast

A comprehensive multi-room audio streaming solution combining Snapcast with a modern React frontend. Supports AirPlay, Bluetooth (A2DP), and Spotify Connect.

## Project Structure

This project consists of two main components:

### Backend (Snapcast Server)
Based on the excellent work by [firefrei/docker-snapcast](https://github.com/firefrei/docker-snapcast) repository.

**Original Author**: Matthias Frei (mf@frei.media)  
**Original Repository**: https://github.com/firefrei/docker-snapcast  
**License**: [Check original repository]

#### Our Modifications
- Added custom metadata processing script (`process-airplay-metadata.sh`)
- Modified Docker configuration for integration with our frontend
- Updated Shairport-Sync configuration
- Enhanced supervisord configuration

### Frontend
Original React/TypeScript application providing:
- Modern web interface for Snapcast control
- Real-time audio synchronization management
- Client device management
- Volume and playback controls

## Attribution

This project builds upon the foundational work of the Snapcast ecosystem:

- **Snapcast**: https://github.com/badaix/snapcast by Johannes Pohl
- **Docker Snapcast Container**: https://github.com/firefrei/docker-snapcast by Matthias Frei
- **Shairport-Sync**: https://github.com/mikebrady/shairport-sync by Mike Brady
- **Librespot**: https://github.com/librespot-org/librespot

## Getting Started

### Prerequisites

- Raspberry Pi (3 or newer recommended) running Raspberry Pi OS Lite (64-bit)
- Docker and Docker Compose installed
- Git for cloning the repository

### One-Time Raspberry Pi Setup

When deploying to a new Raspberry Pi, perform these steps once:

#### 1. Install Docker

```bash
# Install Docker using official script
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker $USER

# Log out and back in for group changes to take effect
```

#### 2. Configure Audio Permissions

Create a udev rule to allow Docker containers to access audio devices:

```bash
# Create udev rule file
echo 'SUBSYSTEM=="sound", MODE="0666"' | sudo tee /etc/udev/rules.d/99-audio-permissions.rules

# Apply the rule
sudo udevadm control --reload-rules
sudo udevadm trigger
```

#### 3. Clone and Deploy

```bash
# Clone the repository
git clone <your-repo-url> ~/Plum-Snapcast
cd ~/Plum-Snapcast/docker

# Create .env file from template (optional)
cp .env.example .env
nano .env  # Edit configuration if needed

# Pull and start containers
sudo docker compose pull
sudo docker compose up -d
```

#### 4. Reboot

```bash
sudo reboot
```

**Note**: The container is fully self-contained and requires no host D-Bus or Avahi configuration. It will work identically across different OS versions.

### Accessing the Application

After deployment:

- **Web Interface**: http://raspberrypi.local:3000 or http://<pi-ip-address>:3000
- **AirPlay Device**: Look for "Plum Audio" in AirPlay devices on iOS/macOS
- **Bluetooth Device**: Look for "Plum Audio" in Bluetooth settings on your phone/device (if enabled)

### Verification

Check that all services are running:

```bash
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status
```

Expected output:
```
avahi              RUNNING
dbus               RUNNING
shairport-sync     RUNNING
snapclient         RUNNING
snapserver         RUNNING
```

### Configuration

Edit `docker/.env` to customize:
- `AIRPLAY_DEVICE_NAME`: Name shown in AirPlay device list
- `BLUETOOTH_ENABLED`: Enable Bluetooth A2DP audio (default: 0, set to 1 to enable)
- `BLUETOOTH_DEVICE_NAME`: Name shown in Bluetooth pairing list
- `BLUETOOTH_ADAPTER`: Bluetooth adapter to use (default: hci0)
- `FRONTEND_PORT`: Web interface port (default: 3000)
- `SNAPCLIENT_SOUNDCARD`: ALSA device for audio output (default: hw:Headphones)

For more details, see [CLAUDE.md](CLAUDE.md).

## License

- Frontend code: [Your chosen license]
- Backend modifications: Same as original docker-snapcast repository
- Original Snapcast components: Retain their respective licenses
