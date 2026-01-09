# Plum-Snapcast

A comprehensive multi-room audio streaming solution combining Snapcast with a modern React frontend. Supports AirPlay, Bluetooth (A2DP), Spotify Connect, and DLNA/UPnP.

## Features

- **Multi-room Audio Synchronization**: Sample-accurate synchronized playback across multiple devices
- **Multi-Instance AirPlay**: Up to 10 simultaneous AirPlay endpoints with independent device names
- **Spotify Connect**: Direct streaming from the Spotify app with metadata and album artwork
- **DLNA/UPnP Support**: Stream from any DLNA/UPnP controller (phones, tablets, media servers)
- **Bluetooth Support**: Pair and stream from Bluetooth devices (A2DP)
- **Hardware Audio Output**: Integrated snapclient outputs to Raspberry Pi 3.5mm jack
- **Modern Web Interface**: Real-time control of streams, clients, and volume
- **Web-based Settings**: Configure integrations, enable/disable services, and customize device names from the browser
- **mDNS Hostname Support**: Access via customizable hostname.local addresses on your local network
- **Metadata Display**: Real-time track information and album artwork for all sources
- **Real-time Playback Position**: Smooth, stutter-free position tracking with server-side interpolation
- **Theme Customization**: Dark/light/system modes with multiple accent color options
- **Dynamic Favicon**: Browser icon updates to match your chosen accent color

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
- Web-based settings and integration control
- Dynamic service enable/disable without container restart
- Theme customization and display preferences

## Attribution

This project builds upon the foundational work of the Snapcast ecosystem:

- **Snapcast**: https://github.com/badaix/snapcast by Johannes Pohl
- **Docker Snapcast Container**: https://github.com/firefrei/docker-snapcast by Matthias Frei
- **Shairport-Sync**: https://github.com/mikebrady/shairport-sync by Mike Brady
- **Spotifyd**: https://github.com/Spotifyd/spotifyd
- **Librespot**: https://github.com/librespot-org/librespot
- **gmrender-resurrect**: https://github.com/hzeller/gmrender-resurrect by Henner Zeller

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

#### 3. Configure Audio HATs (Optional)

If you're using a Raspberry Pi HAT (Hardware Attached on Top) audio board, you'll need to configure it before deploying the container. Raspberry Pi OS doesn't auto-detect audio HATs - they require explicit device tree overlay configuration.

**Supported HATs**: Plum-Snapcast automatically detects and supports HATs including HiFiBerry, IQaudio, Pisound, AudioInjector, JustBoom, and others. HATs will appear with a "(HAT)" suffix in the Audio Settings within the web UI.

##### Configuration Steps:

1. Edit the Raspberry Pi boot configuration file:
   ```bash
   sudo nano /boot/firmware/config.txt
   # On older systems, use: sudo nano /boot/config.txt
   ```

2. Add the appropriate device tree overlay for your HAT model. For example, HiFiBerry AMP60/AMP100:
   ```bash
   # /boot/firmware/config.txt
   dtoverlay=hifiberry-amp100
   ```

3. Save the file and reboot:
   ```bash
   sudo reboot
   ```

##### Verification:

After rebooting, verify your HAT is detected:
```bash
# Check available audio devices
aplay -l
```

Your HAT should appear in the list. You can also verify detection in the Plum-Snapcast web UI under **Settings → Audio** - HATs will be labeled with "(HAT)".

##### Troubleshooting:

- **HAT not detected**: Verify the overlay name matches your HAT model exactly
- **Check kernel logs**: Run `dmesg | grep -i audio` to see if the HAT was initialized
- **Consult documentation**: Different HAT models may require different overlay names or additional parameters

**Resources**:
- HiFiBerry Documentation: https://www.hifiberry.com/docs/
- Raspberry Pi HAT Documentation: https://www.raspberrypi.com/documentation/accessories/

#### 4. Clone and Deploy

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

#### 5. Reboot

```bash
sudo reboot
```

**Note**: The container runs its own D-Bus and Avahi daemons. The only host requirement is that the host's Avahi daemon must be disabled (the fresh-pi-setup.sh script handles this automatically).

### Accessing the Application

After deployment:

- **Web Interface**:
  - http://plum-snapcast.local:3000 (default mDNS hostname)
  - http://raspberrypi.local:3000 (host's mDNS name)
  - http://<pi-ip-address>:3000
  - The hostname is configurable in Settings → About
- **AirPlay Devices**: Look for "Plum Audio" (or your custom names) in AirPlay devices on iOS/macOS
  - Manage multiple AirPlay endpoints in Settings → Integrations → AirPlay
  - Each endpoint appears as a separate AirPlay device with its own name
- **Spotify Connect**: Look for "Plum Audio" in Spotify's device list (enable in Settings → Integrations)
- **DLNA/UPnP Renderer**: Look for "Plum Audio" in your DLNA controller app (enable in Settings → Integrations)
- **Bluetooth Device**: Look for "Plum Audio" in Bluetooth settings on your phone/device (enable in Settings → Integrations)

### Verification

Check that all services are running:

```bash
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status
```

Expected output:
```
avahi                          RUNNING
gmrender                       RUNNING (if DLNA enabled)
mosquitto                      RUNNING
spotifyd                       RUNNING (if Spotify enabled)
shairport-sync-1               RUNNING (AirPlay endpoint 1)
shairport-sync-2               RUNNING (if additional endpoints configured)
airplay-1-lifecycle-manager    RUNNING
airplay-1-fifo-keeper          RUNNING
snapclient                     RUNNING
snapserver                     RUNNING
```

### Configuration

**Most settings are configured via the web interface** (Settings → Integrations and Settings → About). See the "Web-Based Settings" section below for details.

For advanced configuration or infrastructure settings, edit `docker/.env`:

**Infrastructure:**
- `FRONTEND_PORT`: Web interface port (default: 3000)
- `SNAPCLIENT_SOUNDCARD`: ALSA device for audio output (default: hw:Headphones)
- `TZ`: Timezone (default: America/Los_Angeles)

**Plexamp** (optional, separate container):
- `PLEXAMP_ENABLED`: Enable Plexamp integration (0=disabled, 1=enabled)
- `PLEXAMP_CLAIM_TOKEN`: Plex claim token from https://plex.tv/claim
- `PLEXAMP_SERVER_NAME`: Name shown in Plex (default: "Plum Audio")

**Bluetooth Notes:**
- Provides track metadata (title, artist, album) and media controls (play, pause, skip)
- Album artwork is not currently available (requires BlueZ 5.81+; Alpine currently ships 5.70)
- Auto-pairing mode only (modern devices use SSP, not PIN codes)

**DLNA/UPnP Notes:**
- Compatible with any DLNA/UPnP control point (BubbleUPnP, mConnect, Windows Media Player, etc.)
- Supports metadata (title, artist, album, artwork) and basic playback control
- Automatically discovered on the local network via Avahi

### Web-Based Settings

Once deployed, you can configure most settings through the web interface without editing configuration files:

1. **Open Settings**: Click the gear icon in the bottom-right corner of the web interface
2. **Available Settings**:
   - **Integrations Tab**: Enable/disable and configure AirPlay, Bluetooth, Spotify Connect, and DLNA services
     - Toggle services on/off without restarting the container
     - Update device names in real-time
     - **AirPlay**: Manage up to 10 simultaneous endpoints, each with independent device names
     - Configure Bluetooth discoverability and pairing options
     - Set Spotify bitrate (96, 160, or 320 kbps)
   - **Snapcast Tab**: Manage Snapcast server settings and federation
     - Enable multi-server federation for synchronized playback across locations
     - Configure auto-discovery and local server names
   - **Theme Tab**: Customize appearance (dark/light/system mode, accent colors)
     - Dynamic favicon updates to match your chosen accent color
   - **Visualizer Tab**: Enable experimental audio visualizer
   - **About Tab**: Configure device identity and view system information
     - Set device name (displayed in federation and browser title)
     - Configure mDNS hostname for local network access (e.g., http://your-hostname.local:3000)
     - View version information and links to documentation

**Note**: Settings are persisted to `/app/data/settings.json` in the container and survive restarts. Initial configuration from environment variables (`.env` file) is automatically migrated to the settings system on first run.

For more details, see [CLAUDE.md](CLAUDE.md).

## License

- Frontend code: [Your chosen license]
- Backend modifications: Same as original docker-snapcast repository
- Original Snapcast components: Retain their respective licenses
