# WiFi Setup (Captive Portal)

A host-side service that lets a freshly-imaged Plum-Snapcast Pi be put on WiFi
without console / SSH access. When the Pi has no network connectivity, it
broadcasts its own access point and serves a captive portal so the user can
pick their home WiFi from a phone or laptop.

## How it works

1. `plum-wifi-setup.service` runs as a systemd unit on the **host** (not in
   the Snapcast container — WiFi must be managed at the OS level).
2. Every 5 seconds it polls NetworkManager for connectivity.
3. After **30 seconds offline** it brings `wlan0` up as an access point named
   **`plum-setup`** (WPA2, password **`plumsetup`**) at **192.168.4.1**.
4. A tiny Flask server listens on port 8080; an `iptables` rule redirects
   inbound port-80 traffic on `wlan0` to it. A dnsmasq drop-in is written to
   `/etc/NetworkManager/dnsmasq-shared.d/` that resolves all DNS queries to
   the AP IP, so OS-level captive-portal probes hit the setup page.
5. The user picks a network + enters a password. The service tears down the
   AP, calls `nmcli device wifi connect ...`, and verifies that connectivity
   is restored. On failure the AP comes back up so the user can retry.
6. Once online, the daemon goes back to monitoring and the AP stays down.

## Requirements

- Raspberry Pi OS Bookworm (or newer) using **NetworkManager**.
  - On older images (`dhcpcd`-based) switch with
    `sudo raspi-config` → *Advanced Options* → *Network Config* → *NetworkManager*.
- `python3-flask`, `dnsmasq-base`, `iptables` (installed by `install.sh`).
- Root (the daemon shells out to `nmcli` and `iptables`).

## Installing

From a checked-out copy of the repo on the Pi:

```bash
sudo bash scripts/wifi-setup/install.sh
```

This:

- installs runtime deps
- copies the daemon + `setup.html` to `/opt/plum-wifi-setup/`
- installs and enables `plum-wifi-setup.service`

## Using it (end-user flow)

1. Power on the Pi without a wired connection (or after WiFi credentials
   change and stop working).
2. After ~30 seconds, a WiFi network named **`plum-setup`** appears.
3. Join it with the password **`plumsetup`**.
4. Most phones pop up a captive-portal browser automatically. If yours does
   not, open <http://192.168.4.1> manually.
5. Pick your home WiFi, enter the password, tap **Connect**.
6. The page reports success or failure; on success the AP shuts down and the
   Pi is on the new network.

## Operating

```bash
# Service status / live logs
sudo systemctl status   plum-wifi-setup
sudo journalctl -u      plum-wifi-setup -f

# Force the captive portal to come up for testing (drops current WiFi)
sudo nmcli connection down "$(nmcli -t -f NAME,TYPE connection show --active | grep ':wifi' | head -1 | cut -d: -f1)"

# Wipe the AP profile (it will be re-created automatically)
sudo nmcli connection delete plum-setup
```

## Configuration

A few constants live at the top of `plum-wifi-setup.py`:

| Setting | Default | Notes |
|--------|---------|-------|
| `AP_SSID` | `plum-setup` | Broadcast name. |
| `AP_PASSWORD` | `plumsetup` | WPA2 PSK. Must be ≥ 8 chars. |
| `AP_ADDRESS` | `192.168.4.1` | DHCP server / captive portal IP. |
| `CONNECTIVITY_GRACE_SECONDS` | `30` | Offline duration before AP starts. |
| `WIFI_IFACE` env var | `wlan0` | Override for non-standard interface names. |

After editing, restart the service:

```bash
sudo systemctl restart plum-wifi-setup
```

## Troubleshooting

**The AP never appears.**
Check `journalctl -u plum-wifi-setup -f`. Common causes: NetworkManager is
not the active stack, `wlan0` is being held by `wpa_supplicant` from a
non-NM config, or the interface is rfkill-blocked (`rfkill list`).

**The phone joins `plum-setup` but no captive portal pops up.**
The OS probe runs over HTTP/DNS. Make sure `dnsmasq-base` is installed
(`dpkg -l dnsmasq-base`) so NetworkManager's internal dnsmasq picks up the
hijack file at `/etc/NetworkManager/dnsmasq-shared.d/00-plum-captive.conf`.
You can always open <http://192.168.4.1> directly.

**"Joined the network but no connectivity" after Connect.**
The password was probably wrong, or the AP requires a captive-portal sign-in
of its own. Try again, or move the Pi closer to the AP and retry.

**Service interferes when the Pi is already on WiFi.**
It shouldn't — it only activates after 30 seconds with no usable
connection. To disable entirely:

```bash
sudo systemctl disable --now plum-wifi-setup
```

## Files

```
scripts/wifi-setup/
  plum-wifi-setup.py        # Flask daemon + connectivity monitor
  plum-wifi-setup.service   # systemd unit
  install.sh                # host installer
  static/setup.html         # captive portal UI (single file)
```

On the installed Pi everything lives under `/opt/plum-wifi-setup/` plus the
service unit at `/etc/systemd/system/plum-wifi-setup.service`.
