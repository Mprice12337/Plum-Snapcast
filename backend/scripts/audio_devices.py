#!/usr/bin/env python3
"""
Audio Device Manager
Discovers and categorizes ALSA audio devices for input/output configuration
"""

import logging
import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class DeviceType(Enum):
    """Audio device type categories"""
    BUILTIN_HEADPHONES = "BUILTIN_HEADPHONES"
    BUILTIN_HDMI = "BUILTIN_HDMI"
    USB = "USB"
    HAT = "HAT"
    OTHER = "OTHER"


@dataclass
class AudioDevice:
    """Represents an ALSA audio device"""
    card: int
    device: int
    hw_id: str  # e.g., hw:0,0
    hw_name: Optional[str]  # e.g., hw:Headphones
    card_name: str
    device_name: str
    type: DeviceType
    friendly_name: str
    is_available: bool = True

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "card": self.card,
            "device": self.device,
            "hw_id": self.hw_id,
            "hw_name": self.hw_name,
            "card_name": self.card_name,
            "device_name": self.device_name,
            "type": self.type.value,
            "friendly_name": self.friendly_name,
            "is_available": self.is_available
        }


class AudioDeviceManager:
    """Manages ALSA audio device discovery and configuration"""

    # Known HAT identifiers (expandable as needed)
    HAT_IDENTIFIERS = [
        "hifiberry",
        "iqaudio",
        "pisound",
        "audioinjector",
        "justboom",
        "dacplus",
        "digi",
        "amp",
    ]

    def __init__(self):
        pass

    def _run_command(self, cmd: List[str], timeout: int = 10) -> tuple[bool, str]:
        """Run a shell command and return (success, output)"""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            success = result.returncode == 0
            output = result.stdout if success else result.stderr
            return success, output.strip()
        except subprocess.TimeoutExpired:
            logger.error(f"Command timeout: {' '.join(cmd)}")
            return False, "Command timed out"
        except Exception as e:
            logger.error(f"Command error: {e}")
            return False, str(e)

    def _parse_aplay_list(self, output: str) -> List[AudioDevice]:
        """
        Parse output from `aplay -l` command

        Format example:
        card 0: Headphones [bcm2835 Headphones], device 0: bcm2835 Headphones [bcm2835 Headphones]
          Subdevices: 8/8
          Subdevice #0: subdevice #0
        card 1: vc4hdmi [vc4-hdmi], device 0: MAI PCM i2s-hifi-0 [MAI PCM i2s-hifi-0]
          Subdevices: 1/1
          Subdevice #0: subdevice #0
        """
        devices = []

        # Pattern: card N: CardName [CardDescription], device N: DeviceName [DeviceDescription]
        pattern = r'card\s+(\d+):\s+(\S+)\s+\[([^\]]+)\],\s+device\s+(\d+):\s+(\S+.*?)\s+\[([^\]]+)\]'

        for match in re.finditer(pattern, output):
            card = int(match.group(1))
            card_name = match.group(2)
            card_description = match.group(3)
            device = int(match.group(4))
            device_name_raw = match.group(5).strip()
            device_description = match.group(6)

            # Build hw IDs
            hw_id = f"hw:{card},{device}"
            hw_name = self._get_hw_name(card, card_name)

            # Identify device type
            device_type = self._identify_device_type(
                card_name, card_description, device_name_raw, device_description
            )

            # Generate friendly name
            friendly_name = self._generate_friendly_name(
                device_type, card_name, card_description, device_description
            )

            # Create device object
            audio_device = AudioDevice(
                card=card,
                device=device,
                hw_id=hw_id,
                hw_name=hw_name,
                card_name=card_name,
                device_name=device_description,
                type=device_type,
                friendly_name=friendly_name
            )

            devices.append(audio_device)
            logger.debug(f"Found device: {audio_device.friendly_name} ({hw_id})")

        return devices

    def _get_hw_name(self, card: int, card_name: str) -> Optional[str]:
        """
        Get the hw name (e.g., hw:Headphones) if available
        Some devices can be addressed by name instead of number
        """
        # Common named devices on Raspberry Pi
        if card_name.lower() in ["headphones", "vc4hdmi", "vc4-hdmi"]:
            return f"hw:{card_name}"
        return None

    def _identify_device_type(
        self,
        card_name: str,
        card_description: str,
        device_name: str,
        device_description: str
    ) -> DeviceType:
        """Categorize audio device based on identifiers"""

        # Combine all identifiers for matching
        combined = f"{card_name} {card_description} {device_name} {device_description}".lower()

        # Check for built-in headphones (Raspberry Pi 3.5mm jack)
        if "headphones" in combined or "bcm2835 headphones" in combined:
            return DeviceType.BUILTIN_HEADPHONES

        # Check for built-in HDMI
        if "hdmi" in combined or "vc4-hdmi" in combined or "vc4hdmi" in combined:
            return DeviceType.BUILTIN_HDMI

        # Check for USB devices
        if "usb" in combined:
            return DeviceType.USB

        # Check for known HAT identifiers
        for hat_id in self.HAT_IDENTIFIERS:
            if hat_id.lower() in combined:
                return DeviceType.HAT

        # Default to OTHER
        return DeviceType.OTHER

    def _generate_friendly_name(
        self,
        device_type: DeviceType,
        card_name: str,
        card_description: str,
        device_description: str
    ) -> str:
        """Generate user-friendly device name"""

        if device_type == DeviceType.BUILTIN_HEADPHONES:
            return "Built-in Headphones (3.5mm Jack)"

        elif device_type == DeviceType.BUILTIN_HDMI:
            return "Built-in HDMI Audio"

        elif device_type == DeviceType.USB:
            # Use device description for USB devices
            # Clean up common patterns
            name = device_description.replace("USB Audio", "").strip()
            if not name:
                name = card_description
            return f"{name} (USB)" if name else "USB Audio Device"

        elif device_type == DeviceType.HAT:
            # Use card description for HATs
            return f"{card_description} (HAT)"

        else:
            # Use device description for other devices
            return device_description if device_description else card_description

    def get_playback_devices(self) -> List[AudioDevice]:
        """Get list of all available ALSA playback devices"""
        logger.info("Scanning for playback devices...")

        success, output = self._run_command(["aplay", "-l"])

        if not success:
            logger.error(f"Failed to list playback devices: {output}")
            return []

        devices = self._parse_aplay_list(output)
        logger.info(f"Found {len(devices)} playback device(s)")

        return devices

    def get_capture_devices(self) -> List[AudioDevice]:
        """Get list of all available ALSA capture devices"""
        logger.info("Scanning for capture devices...")

        success, output = self._run_command(["arecord", "-l"])

        if not success:
            # No capture devices is not an error - many systems don't have mics
            if "no soundcards found" in output.lower():
                logger.info("No capture devices found")
                return []
            logger.warning(f"Failed to list capture devices: {output}")
            return []

        devices = self._parse_aplay_list(output)
        logger.info(f"Found {len(devices)} capture device(s)")

        return devices

    def test_device(self, hw_id: str, is_playback: bool = True) -> tuple[bool, str]:
        """
        Test if a device is accessible and functional

        Args:
            hw_id: Hardware ID (e.g., hw:0,0 or hw:Headphones)
            is_playback: True for playback device, False for capture

        Returns:
            (success, message)
        """
        logger.info(f"Testing {'playback' if is_playback else 'capture'} device: {hw_id}")

        if is_playback:
            # Use speaker-test with very short duration (1 loop)
            cmd = [
                "speaker-test",
                "-D", hw_id,
                "-c", "2",  # 2 channels (stereo)
                "-t", "wav",  # WAV test (recognizable sound)
                "-l", "1"  # 1 loop only (very brief)
            ]
        else:
            # Use arecord to test capture (1 second of silence)
            cmd = [
                "arecord",
                "-D", hw_id,
                "-d", "1",  # 1 second duration
                "-f", "S16_LE",
                "-r", "44100",
                "/dev/null"  # Discard output
            ]

        success, output = self._run_command(cmd, timeout=15)

        if success:
            logger.info(f"Device {hw_id} test passed")
            return True, "Device is accessible"
        else:
            logger.error(f"Device {hw_id} test failed: {output}")
            return False, f"Device test failed: {output}"

    def get_device_by_hw_id(self, hw_id: str, is_playback: bool = True) -> Optional[AudioDevice]:
        """
        Get device information by hardware ID

        Args:
            hw_id: Hardware ID (e.g., hw:0,0 or hw:Headphones)
            is_playback: True for playback device, False for capture

        Returns:
            AudioDevice if found, None otherwise
        """
        devices = self.get_playback_devices() if is_playback else self.get_capture_devices()

        # Try exact match on hw_id
        for device in devices:
            if device.hw_id == hw_id:
                return device

        # Try match on hw_name
        for device in devices:
            if device.hw_name == hw_id:
                return device

        return None


# For standalone testing
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    manager = AudioDeviceManager()

    print("\n=== Playback Devices ===")
    playback_devices = manager.get_playback_devices()
    for device in playback_devices:
        print(f"\n{device.friendly_name}")
        print(f"  HW ID: {device.hw_id}")
        if device.hw_name:
            print(f"  HW Name: {device.hw_name}")
        print(f"  Type: {device.type.value}")
        print(f"  Card: {device.card}, Device: {device.device}")
        print(f"  Card Name: {device.card_name}")
        print(f"  Device Name: {device.device_name}")

    print("\n\n=== Capture Devices ===")
    capture_devices = manager.get_capture_devices()
    if capture_devices:
        for device in capture_devices:
            print(f"\n{device.friendly_name}")
            print(f"  HW ID: {device.hw_id}")
            if device.hw_name:
                print(f"  HW Name: {device.hw_name}")
            print(f"  Type: {device.type.value}")
    else:
        print("No capture devices found")
