#!/usr/bin/env python3
"""
Bluetooth Auto-Pairing Agent for Plum-Snapcast

This agent handles Bluetooth pairing requests with configurable security:
- If BLUETOOTH_PAIRING_CODE is set: Requires that specific PIN code
- If not set: Auto-accepts all pairing requests (less secure, easier setup)

Designed for headless audio receivers where manual pairing isn't possible.
"""

import os
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

BUS_NAME = 'org.bluez'
AGENT_INTERFACE = 'org.bluez.Agent1'
AGENT_PATH = "/plum/snapcast/agent"

# Read pairing code from environment variable
PAIRING_CODE = os.environ.get('BLUETOOTH_PAIRING_CODE', '')


class AutoPairAgent(dbus.service.Object):
    """
    BlueZ Agent that handles pairing with configurable PIN code.
    Implements the org.bluez.Agent1 D-Bus interface.
    """

    def __init__(self, bus, path, pairing_code=''):
        super().__init__(bus, path)
        self.pairing_code = pairing_code
        if self.pairing_code:
            print(f"Bluetooth agent initialized with static PIN code: {self.pairing_code}")
            print("Devices must enter this code to pair")
        else:
            print(f"Bluetooth agent initialized in auto-accept mode (no PIN required)")
            print("WARNING: Any device can pair without authentication")

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        """Auto-authorize all service connections"""
        print(f"Auto-authorizing service {uuid} for device {device}")
        return

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        """Return the configured PIN for devices that require it"""
        pin = self.pairing_code if self.pairing_code else "0000"
        print(f"Providing PIN '{pin}' for device {device}")
        return pin

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        """Return the configured passkey as a number"""
        # Convert PIN string to number (default 0 if not a valid number)
        try:
            passkey = int(self.pairing_code) if self.pairing_code and self.pairing_code.isdigit() else 0
        except ValueError:
            passkey = 0
        print(f"Providing passkey {passkey} for device {device}")
        return dbus.UInt32(passkey)

    @dbus.service.method(AGENT_INTERFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        """Display passkey (just log it)"""
        print(f"Passkey for {device}: {passkey:06d} (entered: {entered})")

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        """Display PIN code (just log it)"""
        print(f"PIN code for {device}: {pincode}")

    @dbus.service.method(AGENT_INTERFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        """
        Handle SSP (Secure Simple Pairing) numeric comparison requests.

        If a PIN code is configured, we REJECT this to force PIN entry mode.
        If no PIN is configured, we auto-accept for easy pairing.
        """
        if self.pairing_code:
            # Reject SSP to force the device to use PIN entry instead
            print(f"Rejecting SSP confirmation for {device} (passkey {passkey:06d}) - PIN code required")
            raise dbus.exceptions.DBusException(
                "org.bluez.Error.Rejected",
                "PIN code entry required - use configured PIN"
            )
        else:
            # Auto-accept if no PIN configured
            print(f"Auto-confirming pairing for {device} with passkey {passkey:06d}")
            return

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        """Auto-authorize all requests"""
        print(f"Auto-authorizing {device}")
        return

    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Cancel(self):
        """Handle cancellation"""
        print("Pairing request canceled")


def main():
    """Main function to register and run the agent"""
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    bus = dbus.SystemBus()
    agent = AutoPairAgent(bus, AGENT_PATH, pairing_code=PAIRING_CODE)

    try:
        # Get the BlueZ agent manager
        obj = bus.get_object(BUS_NAME, "/org/bluez")
        manager = dbus.Interface(obj, "org.bluez.AgentManager1")

        # Register our agent with appropriate capability
        # Use "KeyboardOnly" if PIN is set (forces PIN entry, rejects SSP)
        # Use "NoInputNoOutput" for auto-accept
        capability = "KeyboardOnly" if PAIRING_CODE else "NoInputNoOutput"
        manager.RegisterAgent(AGENT_PATH, capability)
        print(f"Agent registered with BlueZ (capability: {capability})")

        # Request to be the default agent
        manager.RequestDefaultAgent(AGENT_PATH)
        print("Set as default agent")

        print("Bluetooth pairing agent is running...")
        if PAIRING_CODE:
            print(f"Pairing mode: PIN code required (code: {PAIRING_CODE})")
        else:
            print("Pairing mode: Auto-accept (no PIN required)")

        # Run the main loop
        mainloop = GLib.MainLoop()
        mainloop.run()

    except KeyboardInterrupt:
        print("\nShutting down agent...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            manager.UnregisterAgent(AGENT_PATH)
            print("Agent unregistered")
        except:
            pass


if __name__ == "__main__":
    main()
