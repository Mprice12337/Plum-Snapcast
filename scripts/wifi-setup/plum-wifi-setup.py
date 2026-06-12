#!/usr/bin/env python3
"""
Plum WiFi Setup Daemon

Runs on the Raspberry Pi host (not inside the Plum-Snapcast container). When the
device has no usable network for CONNECTIVITY_GRACE_SECONDS, brings up wlan0 as
an open-broadcast WiFi access point ("plum-setup") and serves a captive portal
on http://192.168.4.1 so the user can pick a WiFi network and enter a password
from any phone or laptop. Once a valid connection is established the AP is torn
down automatically.

Requires NetworkManager and dnsmasq-base. Must run as root.
"""

import logging
import os
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional

from flask import Flask, jsonify, redirect, request, send_from_directory


# --- Configuration ---------------------------------------------------------

AP_CON_NAME = "plum-setup"
AP_SSID = "plum-setup"
AP_PASSWORD = "plumsetup"          # WPA2-PSK; must be >= 8 chars.
AP_ADDRESS = "192.168.4.1"
AP_PREFIX = 24
WIFI_IFACE = os.environ.get("PLUM_WIFI_IFACE", "wlan0")

HTTP_PORT = 8080                   # iptables redirects port 80 -> here
CONNECTIVITY_CHECK_INTERVAL = 5    # seconds between connectivity polls
CONNECTIVITY_GRACE_SECONDS = 30    # how long offline before AP comes up

DNSMASQ_DROPIN_PATH = "/etc/NetworkManager/dnsmasq-shared.d/00-plum-captive.conf"
DNSMASQ_DROPIN_CONTENT = (
    "# Written by plum-wifi-setup while the captive portal is active.\n"
    "# Resolves every DNS query to the AP IP so probes hit our portal.\n"
    f"address=/#/{AP_ADDRESS}\n"
    "no-resolv\n"
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


# --- Logging ---------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("plum-wifi-setup")


# --- Shell helpers ---------------------------------------------------------

def run(cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    log.debug("run: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _split_nmcli_terse(line: str) -> List[str]:
    """nmcli -t escapes ':' inside fields as '\\:'. Split safely."""
    parts: List[str] = []
    buf = ""
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line) and line[i + 1] == ":":
            buf += ":"
            i += 2
            continue
        if c == ":":
            parts.append(buf)
            buf = ""
            i += 1
            continue
        buf += c
        i += 1
    parts.append(buf)
    return parts


# --- NetworkManager wrappers ----------------------------------------------

def is_online() -> bool:
    """True if any wifi or ethernet device has a real (non-AP) connection."""
    r = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
    if r.returncode != 0:
        return False
    for line in r.stdout.strip().splitlines():
        parts = _split_nmcli_terse(line)
        if len(parts) < 4:
            continue
        _device, dtype, dstate, con = parts[0], parts[1], parts[2], parts[3]
        if dtype not in ("wifi", "ethernet"):
            continue
        if dstate != "connected":
            continue
        if con and con != AP_CON_NAME:
            return True
    return False


def scan_wifi() -> List[Dict]:
    run(["nmcli", "device", "wifi", "rescan", "ifname", WIFI_IFACE], timeout=15)
    r = run([
        "nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE",
        "device", "wifi", "list", "ifname", WIFI_IFACE,
    ])
    by_ssid: Dict[str, Dict] = {}
    for line in r.stdout.strip().splitlines():
        parts = _split_nmcli_terse(line)
        if len(parts) < 4:
            continue
        ssid, signal, security, in_use = parts[0], parts[1], parts[2], parts[3]
        if not ssid or ssid == "--" or ssid == AP_SSID:
            continue
        try:
            sig = int(signal)
        except ValueError:
            sig = 0
        existing = by_ssid.get(ssid)
        if existing and existing["signal"] >= sig:
            continue
        by_ssid[ssid] = {
            "ssid": ssid,
            "signal": sig,
            "security": security or "--",
            "in_use": in_use == "*",
        }
    return sorted(by_ssid.values(), key=lambda n: n["signal"], reverse=True)


def _ensure_ap_profile() -> None:
    r = run(["nmcli", "-t", "-f", "NAME", "connection", "show"])
    existing = {line.strip() for line in r.stdout.splitlines()}
    if AP_CON_NAME not in existing:
        run([
            "nmcli", "connection", "add", "type", "wifi",
            "ifname", WIFI_IFACE, "con-name", AP_CON_NAME,
            "autoconnect", "no", "ssid", AP_SSID,
        ])
    run([
        "nmcli", "connection", "modify", AP_CON_NAME,
        "802-11-wireless.mode", "ap",
        "802-11-wireless.band", "bg",
        "ipv4.method", "shared",
        "ipv4.addresses", f"{AP_ADDRESS}/{AP_PREFIX}",
        "ipv6.method", "ignore",
        "wifi-sec.key-mgmt", "wpa-psk",
        "wifi-sec.psk", AP_PASSWORD,
    ])


def _write_dns_hijack() -> None:
    try:
        os.makedirs(os.path.dirname(DNSMASQ_DROPIN_PATH), exist_ok=True)
        with open(DNSMASQ_DROPIN_PATH, "w") as f:
            f.write(DNSMASQ_DROPIN_CONTENT)
    except Exception as e:
        log.warning("Could not write dnsmasq drop-in: %s", e)


def _remove_dns_hijack() -> None:
    try:
        if os.path.exists(DNSMASQ_DROPIN_PATH):
            os.remove(DNSMASQ_DROPIN_PATH)
    except Exception as e:
        log.warning("Could not remove dnsmasq drop-in: %s", e)


def _iptables_add() -> None:
    # Redirect captive-portal HTTP probes to our Flask server. Idempotent: skip
    # if rule already exists.
    check = run([
        "iptables", "-t", "nat", "-C", "PREROUTING",
        "-i", WIFI_IFACE, "-p", "tcp", "--dport", "80",
        "-j", "REDIRECT", "--to-port", str(HTTP_PORT),
    ])
    if check.returncode == 0:
        return
    run([
        "iptables", "-t", "nat", "-A", "PREROUTING",
        "-i", WIFI_IFACE, "-p", "tcp", "--dport", "80",
        "-j", "REDIRECT", "--to-port", str(HTTP_PORT),
    ])


def _iptables_remove() -> None:
    while True:
        r = run([
            "iptables", "-t", "nat", "-D", "PREROUTING",
            "-i", WIFI_IFACE, "-p", "tcp", "--dport", "80",
            "-j", "REDIRECT", "--to-port", str(HTTP_PORT),
        ])
        if r.returncode != 0:
            break


def start_ap() -> bool:
    log.info("Starting AP %s on %s", AP_SSID, WIFI_IFACE)
    _ensure_ap_profile()
    _write_dns_hijack()
    r = run(["nmcli", "connection", "up", AP_CON_NAME], timeout=45)
    if r.returncode != 0:
        log.error("Failed to start AP: %s", r.stderr.strip())
        _remove_dns_hijack()
        return False
    _iptables_add()
    log.info("AP up at http://%s", AP_ADDRESS)
    return True


def stop_ap() -> None:
    log.info("Stopping AP")
    _iptables_remove()
    run(["nmcli", "connection", "down", AP_CON_NAME], timeout=15)
    _remove_dns_hijack()


def connect_to_wifi(ssid: str, password: Optional[str]) -> Dict:
    """Drop the AP, attempt to join `ssid`, verify, and either stay connected
    or restart the AP so the user can retry."""
    log.info("Attempting connection to %s", ssid)
    stop_ap()
    time.sleep(2)
    cmd = ["nmcli", "device", "wifi", "connect", ssid, "ifname", WIFI_IFACE]
    if password:
        cmd += ["password", password]
    r = run(cmd, timeout=60)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "Connection failed").strip()
        log.warning("Connect failed: %s", msg)
        start_ap()
        return {"success": False, "message": msg}
    time.sleep(3)
    if is_online():
        log.info("Connected to %s", ssid)
        return {"success": True, "message": f"Connected to {ssid}"}
    log.warning("Joined %s but no connectivity; restarting AP", ssid)
    start_ap()
    return {
        "success": False,
        "message": "Joined the network but no connectivity. Check password and try again.",
    }


# --- Flask app -------------------------------------------------------------

app = Flask(__name__)

state = {
    "ap_active": False,
    "connecting": False,
    "last_connect_result": None,  # type: Optional[Dict]
}
state_lock = threading.Lock()


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "setup.html")


@app.route("/api/status")
def api_status():
    with state_lock:
        return jsonify({
            "ap_active": state["ap_active"],
            "connecting": state["connecting"],
            "last_connect_result": state["last_connect_result"],
            "online": is_online(),
            "ssid": AP_SSID,
            "address": AP_ADDRESS,
        })


@app.route("/api/scan")
def api_scan():
    try:
        return jsonify({"networks": scan_wifi()})
    except Exception as e:
        log.exception("scan failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/connect", methods=["POST"])
def api_connect():
    body = request.get_json(silent=True) or {}
    ssid = (body.get("ssid") or "").strip()
    password = body.get("password") or ""
    if not ssid:
        return jsonify({"success": False, "message": "SSID required"}), 400

    with state_lock:
        if state["connecting"]:
            return jsonify({"success": False, "message": "Already connecting"}), 409
        state["connecting"] = True
        state["last_connect_result"] = None

    def worker():
        try:
            result = connect_to_wifi(ssid, password)
        except Exception as e:
            log.exception("connect worker failed")
            result = {"success": False, "message": str(e)}
            try:
                start_ap()
            except Exception:
                pass
        with state_lock:
            state["connecting"] = False
            state["last_connect_result"] = result
            state["ap_active"] = not result.get("success", False)

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"success": True, "message": "Connecting..."})


# Captive-portal probe URLs. We send a 302 to the setup page so the OS pops up
# its built-in captive-portal browser. Catch-all does the same for anything else.
_PROBE_PATHS = [
    "/hotspot-detect.html",          # Apple
    "/library/test/success.html",    # Apple legacy
    "/generate_204",                 # Android / Chrome
    "/gen_204",                      # Android
    "/ncsi.txt",                     # Windows
    "/connecttest.txt",              # Windows 10/11
    "/redirect",                     # Windows
]


def _portal_redirect(*_args, **_kwargs):
    return redirect(f"http://{AP_ADDRESS}/", code=302)


for _p in _PROBE_PATHS:
    app.add_url_rule(_p, endpoint=f"probe_{_p}", view_func=_portal_redirect)


@app.route("/<path:_anything>")
def catch_all(_anything):
    return redirect(f"http://{AP_ADDRESS}/", code=302)


# --- Monitor loop ----------------------------------------------------------

def monitor_loop() -> None:
    last_online_ts = time.monotonic()
    while True:
        try:
            with state_lock:
                ap_active = state["ap_active"]
                connecting = state["connecting"]

            if connecting:
                time.sleep(CONNECTIVITY_CHECK_INTERVAL)
                continue

            if ap_active:
                # If a wired interface came up while AP was active, stand down.
                if is_online():
                    log.info("Online via another interface; stopping AP")
                    stop_ap()
                    with state_lock:
                        state["ap_active"] = False
                    last_online_ts = time.monotonic()
                time.sleep(CONNECTIVITY_CHECK_INTERVAL)
                continue

            if is_online():
                last_online_ts = time.monotonic()
            else:
                offline_for = time.monotonic() - last_online_ts
                if offline_for >= CONNECTIVITY_GRACE_SECONDS:
                    log.warning("Offline for %ds; bringing up AP", int(offline_for))
                    if start_ap():
                        with state_lock:
                            state["ap_active"] = True
        except Exception as e:
            log.exception("monitor loop error: %s", e)
        time.sleep(CONNECTIVITY_CHECK_INTERVAL)


def main() -> None:
    if os.geteuid() != 0:
        log.error("plum-wifi-setup must run as root (need nmcli / iptables)")
        sys.exit(1)
    log.info("plum-wifi-setup starting (iface=%s, port=%d)", WIFI_IFACE, HTTP_PORT)
    threading.Thread(target=monitor_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=HTTP_PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
