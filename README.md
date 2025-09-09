# Plum-Snapcast

A comprehensive multi-room audio streaming solution combining Snapcast with a modern React frontend.

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

[Add your setup instructions here]

## License

- Frontend code: [Your chosen license]
- Backend modifications: Same as original docker-snapcast repository
- Original Snapcast components: Retain their respective licenses
