# Developer Setup Guide - Plum-Snapcast

> **Purpose**: This guide contains the setup tasks and configurations that developers should complete before working on the Plum-Snapcast project. Once this setup is complete, you can develop and test changes locally before deploying to Raspberry Pi hardware.

---

## Table of Contents
1. [Initial Project Setup](#initial-project-setup)
2. [Git Configuration](#git-configuration)
3. [Development Environment](#development-environment)
4. [Docker Setup](#docker-setup)
5. [Frontend Development](#frontend-development)
6. [Raspberry Pi Deployment](#raspberry-pi-deployment)
7. [Claude Code Installation](#claude-code-installation)
8. [Testing and Verification](#testing-and-verification)
9. [Handoff Checklist](#handoff-checklist)

---

## Initial Project Setup

### 1. Clone and Verify Repository

```bash
# Clone the repository
git clone <your-repo-url> Plum-Snapcast
cd Plum-Snapcast

# Verify you're on the correct branch
git branch -a
# Should show: * main
```

### 2. Project Folder Structure

The project already has the required folder structure:

```
├── _resources/          # Development references (NOT in git)
├── docs/                # Project documentation
│   ├── ARCHITECTURE.md  # System architecture
│   ├── CLAUDE.md        # Claude Code configuration
│   ├── DEV-SETUP.md     # This file
│   ├── QUICK-REFERENCE.md  # Quick reference
│   └── original/        # Archived documentation
├── backend/             # Docker container backend
├── frontend/            # React/TypeScript web app
├── docker/              # Docker Compose orchestration
├── scripts/             # Helper scripts
└── README.md            # Main documentation
```

**Verify _resources/ is in .gitignore:**
```bash
cat .gitignore | grep _resources
# Should show: _resources/
```

If not present, add it:
```bash
echo "_resources/" >> .gitignore
```

### 3. Understanding the Architecture

Before developing, read these key documents:

1. **README.md** - Project overview and quick start
2. **docs/ARCHITECTURE.md** - Detailed system architecture
3. **docs/CLAUDE.md** - Development conventions and patterns

**Key Architecture Concepts:**
- Single Docker container runs all backend services (snapserver, snapclient, shairport-sync, librespot)
- Services managed by supervisord for process control
- Audio flows through FIFO pipes from sources to snapserver
- Snapclient outputs audio to Raspberry Pi 3.5mm jack (hw:Headphones)
- **Critical**: Host provides D-Bus socket, container runs Avahi daemon
- Frontend is React/TypeScript with WebSocket JSON-RPC communication

---

## Git Configuration

### 1. Set Up Git for Clean History

```bash
# Use rebase by default to maintain linear history
git config pull.rebase true

# Or create custom aliases
git config alias.pr 'pull --rebase'
git config alias.sync 'pull --rebase origin main'
```

**Why**: Keeps commit history linear and clean. Avoids merge commits.

### 2. Configure Git User Info

```bash
git config user.name "Your Name"
git config user.email "your.email@example.com"

# Optional: Sign commits with GPG
git config commit.gpgsign true
```

### 3. Branch Naming Conventions

When creating feature branches:
```bash
# Feature branches
git checkout -b feature/add-album-artwork

# Bug fixes
git checkout -b bugfix/fix-audio-permissions

# Documentation
git checkout -b docs/update-architecture

# Refactoring
git checkout -b refactor/simplify-websocket-logic
```

---

## Development Environment

### 1. Required Software

**Essentials:**
- **Docker Desktop** - For building and testing containers
- **Docker Compose** - For orchestrating services
- **Node.js** (v18+) - For frontend development
- **npm** (v9+) - Package management
- **Git** - Version control

**Optional but Recommended:**
- **VS Code** or your preferred IDE
- **Prettier** extension for code formatting
- **ESLint** extension for linting
- **Docker** extension for container management

### 2. IDE Setup (VS Code Example)

**Recommended Extensions:**
```bash
# Install via VS Code Extensions or command line
code --install-extension dbaeumer.vscode-eslint
code --install-extension esbenp.prettier-vscode
code --install-extension ms-azuretools.vscode-docker
code --install-extension bradlc.vscode-tailwindcss
```

**VS Code Settings (Workspace):**
Create `.vscode/settings.json`:
```json
{
  "editor.formatOnSave": true,
  "editor.defaultFormatter": "esbenp.prettier-vscode",
  "editor.codeActionsOnSave": {
    "source.fixAll.eslint": true
  },
  "typescript.tsdk": "frontend/node_modules/typescript/lib"
}
```

### 3. Environment Configuration

**Backend Environment Variables:**
The backend uses environment variables for configuration. Create `docker/.env`:

```bash
cd docker
cp .env.example .env
nano .env  # Edit with your preferences
```

**Example Configuration:**
```bash
# AirPlay Configuration
AIRPLAY_CONFIG_ENABLED=1
AIRPLAY_DEVICE_NAME=Plum Audio Dev
AIRPLAY_SOURCE_NAME=Airplay

# Snapclient Configuration (integrated audio output)
SNAPCLIENT_ENABLED=1
SNAPCLIENT_HOST=localhost
SNAPCLIENT_SOUNDCARD=hw:Headphones
SNAPCLIENT_LATENCY=0

# Spotify Connect (optional)
SPOTIFY_CONFIG_ENABLED=0
SPOTIFY_DEVICE_NAME=Plum Snapcast
SPOTIFY_BITRATE=320

# HTTPS
HTTPS_ENABLED=1
SKIP_CERT_GENERATION=0

# General
TZ=America/New_York
FRONTEND_PORT=3000
```

**Frontend Environment Variables:**
The frontend uses Vite's environment variable system. Create `frontend/.env.local`:

```bash
cd frontend
cat > .env.local << EOF
VITE_SNAPCAST_HOST=localhost
VITE_SNAPCAST_PORT=1788
EOF
```

---

## Docker Setup

### 1. Install Docker

**macOS:**
```bash
# Download Docker Desktop from https://www.docker.com/products/docker-desktop
# Or install via Homebrew
brew install --cask docker
```

**Linux:**
```bash
# Install Docker using official script
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker $USER

# Log out and back in for group changes to take effect
```

**Verify Installation:**
```bash
docker --version
docker-compose --version
```

### 2. Configure Docker for Multi-Architecture Builds

The project builds for both amd64 (development) and arm64 (Raspberry Pi):

```bash
# Create and use buildx builder
docker buildx create --name multiarch --driver docker-container --use
docker buildx inspect --bootstrap

# Verify platforms
docker buildx inspect multiarch
# Should show: Platforms: linux/arm64, linux/amd64
```

### 3. Build Backend Image Locally

```bash
cd docker
bash build-and-push.sh

# This will:
# 1. Build for both amd64 and arm64
# 2. Push to Docker Hub (requires login)
# 3. Take 15-30 minutes on first build
```

**For faster local development (amd64 only):**
```bash
cd backend
docker build -t plum-snapcast-server:dev .
```

### 4. Test Backend Locally (Docker Compose)

**Note**: On macOS/Linux desktop, the integrated snapclient won't produce audio (no hw:Headphones device), but you can verify all services start correctly.

```bash
cd docker

# Start all containers
docker compose up -d

# View logs
docker compose logs -f

# Check all services running
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status

# Expected output:
# avahi              RUNNING
# shairport-sync     RUNNING
# snapserver         RUNNING
# snapclient         RUNNING (will fail on macOS - no audio device)
```

**Troubleshooting on macOS/Linux:**
- **snapclient FATAL**: Expected - no `hw:Headphones` on desktop. Ignore.
- **Avahi conflicts**: Disable host's Avahi if running
- **D-Bus errors**: Ensure host D-Bus is running (Linux only)

### 5. Docker Commands Reference

```bash
# Build and deployment
cd docker && bash build-and-push.sh         # Full multi-arch build
cd backend && docker build -t plum:dev .    # Quick local build

# Container management
docker compose up -d                         # Start containers
docker compose down                          # Stop containers
docker compose restart                       # Restart all services
docker compose logs -f                       # View logs

# Service management (inside container)
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf restart shairport-sync
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -f snapserver

# Shell access
docker exec -it plum-snapcast-server sh

# View specific logs
docker logs plum-snapcast-server | grep -i error
docker exec plum-snapcast-server cat /var/log/supervisor/supervisord.log
```

---

## Frontend Development

### 1. Install Dependencies

```bash
cd frontend
npm install

# Verify installation
npm list react react-dom typescript vite
```

### 2. Start Development Server

```bash
npm run dev

# Output:
#   VITE v6.2.0  ready in 523 ms
#
#   ➜  Local:   http://localhost:5173/
#   ➜  Network: use --host to expose
```

Open browser to `http://localhost:5173` to see the web interface.

### 3. Development Workflow

**Frontend File Structure:**
```
frontend/
├── src/
│   ├── components/              # React components
│   │   ├── NowPlaying.tsx       # Currently playing display
│   │   ├── PlayerControls.tsx   # Playback controls
│   │   ├── StreamSelector.tsx   # Source selection
│   │   ├── ClientManager.tsx    # Device management
│   │   └── Settings.tsx         # Application settings
│   ├── services/                # Backend communication
│   │   ├── snapcastService.ts   # WebSocket JSON-RPC client
│   │   └── snapcastDataService.ts  # Data transformation
│   ├── hooks/                   # Custom React hooks
│   │   └── useAudioSync.ts      # Audio progress tracking
│   ├── App.tsx                  # Main application
│   ├── types.ts                 # TypeScript definitions
│   └── main.tsx                 # Entry point
├── public/                      # Static assets
├── vite.config.ts              # Vite configuration
├── tsconfig.json               # TypeScript configuration
└── package.json                # Dependencies
```

**Making Changes:**
1. Edit files in `frontend/src/`
2. Vite hot-reloads changes automatically
3. Check browser console for errors
4. TypeScript errors appear in terminal

### 4. Frontend Commands

```bash
# Development
npm run dev          # Start dev server with HMR
npm run build        # Production build
npm run preview      # Preview production build

# Code Quality
npm run lint         # Run ESLint (if configured)
npm run format       # Format with Prettier (if configured)

# Type Checking
npx tsc --noEmit     # Type check without building
```

### 5. WebSocket Connection

The frontend connects to Snapcast server via WebSocket:

```typescript
// Default connection (from snapcastService.ts)
const url = 'wss://localhost:1788/jsonrpc';

// During development, ensure backend container is running
// Check connection in browser console
```

**Troubleshooting WebSocket Connection:**
```bash
# Verify snapserver is accessible
curl -k https://localhost:1788/jsonrpc
# Should return WebSocket upgrade error (expected)

# Check snapserver logs
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -f snapserver
```

---

## Raspberry Pi Deployment

### 1. Prepare Raspberry Pi

**Required Hardware:**
- Raspberry Pi 3 or newer
- MicroSD card (16GB+ recommended)
- Power supply
- Speakers or headphones (connected to 3.5mm jack)
- Network connection (Ethernet or WiFi)

**Install Raspberry Pi OS:**
1. Download Raspberry Pi OS Lite (64-bit) from [raspberrypi.com](https://www.raspberrypi.com/software/)
2. Flash to microSD using Raspberry Pi Imager
3. Enable SSH during imaging (Imager → Settings → Enable SSH)
4. Boot Pi and find its IP address

### 2. One-Time Raspberry Pi Setup

**Connect via SSH:**
```bash
ssh pi@raspberrypi.local
# Or: ssh pi@<ip-address>
# Default password: raspberry (change immediately)
```

**Install Docker:**
```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker $USER

# Log out and back in
exit
```

**Configure Audio Permissions:**
```bash
ssh pi@raspberrypi.local

# Create udev rule for audio device access
echo 'SUBSYSTEM=="sound", MODE="0666"' | sudo tee /etc/udev/rules.d/99-audio-permissions.rules

# Apply the rule
sudo udevadm control --reload-rules
sudo udevadm trigger
```

**Disable Host Avahi (Critical):**
```bash
# Disable Avahi to avoid conflicts
sudo systemctl disable avahi-daemon.service
sudo systemctl disable avahi-daemon.socket

# Host D-Bus stays enabled (socket-activated)
```

**Deploy Application:**
```bash
# Clone repository
git clone <repo-url> ~/Plum-Snapcast
cd ~/Plum-Snapcast/docker

# Create .env file
cp .env.example .env
nano .env  # Edit configuration

# Start containers
docker compose pull
docker compose up -d

# Reboot to apply all changes
sudo reboot
```

### 3. Verify Deployment

**After reboot, SSH back in and check:**

```bash
# Check all services running
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status

# Expected output:
# avahi              RUNNING
# shairport-sync     RUNNING
# snapserver         RUNNING
# snapclient         RUNNING
```

**Test Audio Output:**
```bash
# List audio devices
docker exec plum-snapcast-server aplay -l
# Should show: card 0: Headphones [bcm2835 Headphones]

# Test speaker
docker exec plum-snapcast-server speaker-test -D hw:Headphones -c 2 -t wav -l 1
# Should hear test tones from 3.5mm jack
```

**Test AirPlay:**
1. Open Control Center on iPhone/Mac
2. Look for "Plum Audio" (or your configured name)
3. Play audio to it
4. Should hear audio from Pi's 3.5mm jack

**Test Web Interface:**
```bash
# Open browser on another device:
http://raspberrypi.local:3000
# Or: http://<pi-ip-address>:3000

# Should see Plum-Snapcast web interface
```

### 4. Update Deployed Application

```bash
ssh pi@raspberrypi.local
cd ~/Plum-Snapcast/docker

# Pull latest code
git pull

# Update containers
docker compose pull
docker compose up -d

# Verify services restarted
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status
```

---

## Claude Code Installation

### 1. Install Claude Code CLI

**macOS/Linux:**
```bash
curl -fsSL https://cli.claude.ai/install.sh | sh
```

**Verify Installation:**
```bash
claude --version
```

### 2. Authenticate

```bash
claude auth login
# Opens browser for authentication
```

### 3. Configure Claude Code

```bash
# Set default model (Sonnet recommended for daily work)
claude config set model sonnet

# Optional: Use Opus for complex architectural work
# claude config set model opus
```

### 4. Test Claude Code

```bash
# Navigate to project
cd ~/Plum-Snapcast

# Start Claude Code
claude code

# Test with simple prompt:
# "Explain the audio pipeline architecture"
```

### 5. Verify CLAUDE.md Detection

Claude Code automatically loads `CLAUDE.md` from the project root. The file is a symlink to `docs/CLAUDE.md`.

```bash
# Verify symlink exists
ls -la CLAUDE.md
# Should show: CLAUDE.md -> docs/CLAUDE.md

# If missing, create it:
ln -s docs/CLAUDE.md CLAUDE.md
```

---

## Testing and Verification

### 1. Backend Service Tests

```bash
# Check all supervisord services
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status

# Test individual services
docker exec plum-snapcast-server ps aux | grep snapserver
docker exec plum-snapcast-server ps aux | grep snapclient
docker exec plum-snapcast-server ps aux | grep shairport-sync
docker exec plum-snapcast-server ps aux | grep avahi
```

### 2. Audio Pipeline Test

```bash
# 1. Verify audio device accessible
docker exec plum-snapcast-server aplay -l

# 2. Test speaker directly
docker exec plum-snapcast-server speaker-test -D hw:Headphones -c 2 -t wav -l 1

# 3. Play audio via AirPlay
# Use iPhone/Mac to connect to AirPlay device

# 4. Check metadata in web interface
# Open http://localhost:3000 (or Pi IP)
# Should show currently playing track info
```

### 3. WebSocket Communication Test

**In browser console (web interface):**
```javascript
// Monitor WebSocket messages
snapcastService.ws.addEventListener('message', (e) => {
  console.log('WebSocket RX:', JSON.parse(e.data));
});

// Send test request
snapcastService.send({
  id: 999,
  jsonrpc: "2.0",
  method: "Server.GetStatus"
});
```

### 4. Frontend Build Test

```bash
cd frontend
npm run build

# Should complete without errors
# Output: dist/ directory with production files
```

### 5. Multi-Architecture Build Test

```bash
cd docker
bash build-and-push.sh --no-cache

# Verify builds for both architectures:
# - Building for linux/amd64
# - Building for linux/arm64
# Both should complete successfully
```

---

## Common Development Tasks

### Adding a New Frontend Component

```bash
cd frontend/src/components

# Create new component
cat > NewComponent.tsx << 'EOF'
import React from 'react';

interface NewComponentProps {
  title: string;
}

export const NewComponent: React.FC<NewComponentProps> = ({ title }) => {
  return (
    <div className="new-component">
      <h2>{title}</h2>
    </div>
  );
};
EOF

# Add to App.tsx
# Import and use the component
```

### Modifying Backend Configuration

```bash
# Edit configuration generator
nano backend/scripts/generate-config.sh

# Rebuild backend image
cd backend
docker build -t plum-snapcast-server:dev .

# Test locally
cd ../docker
docker compose down
docker compose up -d

# Check logs for errors
docker compose logs -f
```

### Adding Environment Variables

**Backend:**
```bash
# 1. Edit docker/.env.example
nano docker/.env.example

# 2. Update your docker/.env
nano docker/.env

# 3. Update generate-config.sh to use new variable
nano backend/scripts/generate-config.sh

# 4. Rebuild and restart
docker compose down && docker compose up -d
```

**Frontend:**
```bash
# 1. Add to frontend/.env.local
echo "VITE_NEW_VARIABLE=value" >> frontend/.env.local

# 2. Use in TypeScript code
const newVar = import.meta.env.VITE_NEW_VARIABLE;

# 3. Restart dev server
npm run dev
```

---

## Troubleshooting

### Docker Build Issues

**Problem**: Build fails with "permission denied"
```bash
# Solution: Check Docker daemon is running
docker ps

# If not running, start Docker Desktop (macOS)
# Or start Docker service (Linux)
sudo systemctl start docker
```

**Problem**: Multi-architecture build fails
```bash
# Solution: Reinstall buildx
docker buildx rm multiarch
docker buildx create --name multiarch --driver docker-container --use
docker buildx inspect --bootstrap
```

### Frontend Development Issues

**Problem**: `npm run dev` fails
```bash
# Solution: Clear node_modules and reinstall
cd frontend
rm -rf node_modules package-lock.json
npm install
npm run dev
```

**Problem**: WebSocket connection fails
```bash
# Solution: Verify backend is running
docker compose ps

# Check snapserver is accessible
curl -k https://localhost:1788/jsonrpc

# Restart backend
docker compose restart
```

### Raspberry Pi Deployment Issues

**Problem**: No audio from 3.5mm jack
```bash
# Solution 1: Verify audio device
docker exec plum-snapcast-server aplay -l

# Solution 2: Check snapclient is running
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status snapclient

# Solution 3: Verify audio permissions
ls -la /dev/snd/
# All should be rw-rw-rw- (666)

# If not, fix permissions:
sudo chmod 666 /dev/snd/*
sudo udevadm control --reload-rules && sudo udevadm trigger
docker compose restart
```

**Problem**: AirPlay device not visible
```bash
# Solution: Check Avahi is running
docker exec plum-snapcast-server ps aux | grep avahi

# Verify host Avahi is disabled
sudo systemctl status avahi-daemon.service
# Should show: disabled

# Check D-Bus socket accessible
docker exec plum-snapcast-server test -S /var/run/dbus/system_bus_socket && echo "OK" || echo "FAIL"

# Restart container
docker compose restart
```

---

## Handoff Checklist

Before starting active development, ensure:

### ✅ Environment Setup
- [ ] Docker installed and running
- [ ] Docker buildx configured for multi-arch
- [ ] Node.js and npm installed
- [ ] Git configured with rebase enabled
- [ ] IDE/editor set up with extensions

### ✅ Project Setup
- [ ] Repository cloned
- [ ] `docker/.env` created from template
- [ ] `frontend/.env.local` created
- [ ] Dependencies installed (`frontend/npm install`)
- [ ] Backend builds successfully
- [ ] Frontend dev server starts successfully

### ✅ Docker Verification
- [ ] Backend container builds locally
- [ ] `docker compose up -d` starts successfully
- [ ] All supervisord services show RUNNING (except snapclient on desktop)
- [ ] Frontend can connect to backend WebSocket

### ✅ Documentation
- [ ] Read README.md
- [ ] Read docs/ARCHITECTURE.md
- [ ] Read docs/CLAUDE.md
- [ ] Understand critical D-Bus/Avahi architecture pattern
- [ ] Familiar with audio pipeline flow

### ✅ Claude Code Ready
- [ ] Claude Code CLI installed
- [ ] Authenticated with Claude.ai
- [ ] Tested with simple prompt
- [ ] CLAUDE.md symlink verified

### ✅ Optional: Raspberry Pi
- [ ] Raspberry Pi prepared with OS
- [ ] Docker installed on Pi
- [ ] Audio permissions configured
- [ ] Host Avahi disabled
- [ ] Application deployed and tested
- [ ] AirPlay working
- [ ] Web interface accessible

---

## Next Steps

Once setup is complete:

1. **Explore the Codebase**: Understand project structure and key files
2. **Make Small Changes**: Start with simple UI tweaks or documentation updates
3. **Test Locally**: Use Docker Compose for backend, npm dev server for frontend
4. **Deploy to Pi**: Test on actual hardware before pushing
5. **Use Claude Code**: Let Claude help with complex tasks after you've established familiarity

### Recommended First Tasks

**Easy:**
- Update frontend styling or theme colors
- Add new environment variable documentation
- Improve error messages in UI

**Medium:**
- Add new React component for additional metadata
- Enhance WebSocket reconnection logic
- Improve supervisord logging

**Advanced:**
- Add new audio source (requires backend changes)
- Implement multi-room support
- Add authentication layer

---

## Resources

- **Snapcast Documentation**: https://github.com/badaix/snapcast
- **Snapcast JSON-RPC API**: https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/
- **React Documentation**: https://react.dev
- **Vite Documentation**: https://vitejs.dev
- **Docker Documentation**: https://docs.docker.com
- **Alpine Linux**: https://pkgs.alpinelinux.org/
- **Claude Code**: https://docs.claude.com/en/docs/claude-code

---

## Getting Help

**For Project-Specific Questions:**
- Review docs/ARCHITECTURE.md for architectural decisions
- Check docs/QUICK-REFERENCE.md for common commands
- Ask Claude Code: "Help me understand [specific component]"

**For Technical Issues:**
- Check Docker logs: `docker compose logs -f`
- Check supervisord logs: `docker exec plum-snapcast-server cat /var/log/supervisor/supervisord.log`
- Review docs/QUICK-REFERENCE.md troubleshooting section

**For Claude Code Help:**
- Run `claude --help`
- Visit https://docs.claude.com/en/docs/claude-code
- Ask Claude: "How do I [accomplish task]?"

---

**Questions or Issues?**

Contact: [Your contact information]
Repository Issues: [GitHub issues URL]
