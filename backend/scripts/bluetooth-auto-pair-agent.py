#!/usr/bin/env python3
"""
Bluetooth Auto-Pairing Agent for Plum-Snapcast

This agent automatically accepts all Bluetooth pairing requests
without requiring user confirmation. Designed for headless audio
receivers where manual pairing confirmation isn't possible.
"""

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

BUS_NAME = 'org.bluez'
AGENT_INTERFACE = 'org.bluez.Agent1'
AGENT_PATH = "/plum/snapcast/agent"


class AutoPairAgent(dbus.service.Object):
    """
    BlueZ Agent that auto-accepts all pairing requests.
    Implements the org.bluez.Agent1 D-Bus interface.
    """

    def __init__(self, bus, path):
        super().__init__(bus, path)
        print(f"Bluetooth auto-pair agent initialized at {path}")

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        """Auto-authorize all service connections"""
        print(f"Auto-authorizing service {uuid} for device {device}")
        return

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        """Return a default PIN for devices that require it"""
        print(f"Auto-providing PIN '0000' for device {device}")
        return "0000"

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        """Return a default passkey"""
        print(f"Auto-providing passkey 0 for device {device}")
        return dbus.UInt32(0)

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
        """Auto-confirm all pairing requests"""
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
    agent = AutoPairAgent(bus, AGENT_PATH)

    try:
        # Get the BlueZ agent manager
        obj = bus.get_object(BUS_NAME, "/org/bluez")
        manager = dbus.Interface(obj, "org.bluez.AgentManager1")

        # Register our agent
        manager.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
        print("Agent registered with BlueZ")

        # Request to be the default agent
        manager.RequestDefaultAgent(AGENT_PATH)
        print("Set as default agent")

        print("Bluetooth auto-pair agent is running...")
        print("All pairing requests will be automatically accepted")

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
