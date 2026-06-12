#!/usr/bin/env python3
"""
Auto-Switch Service for Plum-Snapcast

Monitors Snapcast stream activity and automatically switches Snapcast groups
to newly-active local sources (localActivity mode). Also supports slave mode
where this unit follows another unit's active stream via snapclient target
switching.

Behaviour:
- Local activity: On Server.OnUpdate, detect new non-none streams and switch
  any group currently on a none-* stream to the new stream.
- Slave mode: Connect to a master unit's WebSocket. When the master's groups
  leave the none stream, repoint local snapclient to the master's snapserver
  so audio plays in sync. When the master goes idle, or a local source
  connects, revert snapclient back to localhost.
"""

import http.client
import json
import os
import re
import subprocess
import sys
import threading
import time
from typing import Optional

import websocket

SNAPSERVER_HOST = "localhost"
SNAPSERVER_HTTP_PORT = 1780
SNAPCLIENT_TARGET_FILE = "/app/data/snapclient_target"
SETTINGS_FILE = "/app/data/settings.json"
SUPERVISORD_CONF = "/app/supervisord/supervisord.conf"
LOCAL_STREAM_PORT = 1704


def log(message: str):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} [AutoSwitch] {message}", file=sys.stderr, flush=True)


class SnapserverClient:
    """HTTP JSON-RPC client for a Snapserver instance"""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._request_id = 0

    def _call_rpc(self, method: str, params: dict = None) -> Optional[dict]:
        self._request_id += 1
        request = {"jsonrpc": "2.0", "id": self._request_id, "method": method}
        if params:
            request["params"] = params
        try:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=5)
            conn.request("POST", "/jsonrpc", json.dumps(request),
                         {"Content-Type": "application/json"})
            response = conn.getresponse()
            raw = response.read().decode("utf-8", errors="replace")
            conn.close()
            # AirPlay metadata can contain WTF-8 lone surrogates and raw control
            # characters (e.g. embedded in cover art / track names) that break
            # json.loads. Strip both before parsing.
            raw = raw.encode("utf-8", errors="ignore").decode("utf-8")
            raw = re.sub(r"[\x00-\x1f]", "", raw)
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                # Binary data in stream metadata properties can produce malformed JSON
                # (e.g. unescaped quote bytes in cover art). Strip the metadata field
                # value and retry — the auto-switch service only needs group/stream IDs.
                raw = re.sub(r'"metadata"\s*:\s*\{[^}]*\}', '"metadata":{}', raw)
                raw = re.sub(r'"metadata"\s*:\s*"[^"]*"', '"metadata":""', raw)
                result = json.loads(raw)
            if "error" in result:
                log(f"RPC error ({method}): {result['error']}")
                return None
            return result.get("result")
        except Exception as e:
            log(f"RPC call failed ({method}): {e}")
            return None

    def get_status(self) -> Optional[dict]:
        return self._call_rpc("Server.GetStatus")

    def set_group_stream(self, group_id: str, stream_id: str) -> bool:
        result = self._call_rpc("Group.SetStream", {"id": group_id, "stream_id": stream_id})
        return result is not None


class AutoSwitchService:

    def __init__(self):
        self._settings: dict = {}
        self._settings_lock = threading.Lock()

        self._local_client = SnapserverClient(SNAPSERVER_HOST, SNAPSERVER_HTTP_PORT)

        # Local WS state
        self._local_ws = None
        self._local_running = False
        self._local_known_streams: set = set()  # non-none stream IDs seen so far

        # Slave WS state
        self._slave_ws = None
        self._slave_running = False
        self._slave_following = False       # True while snapclient is targeting master

        # Idle revert hysteresis: don't revert immediately when master goes idle.
        # Track changes cause a brief idle period (stream removed then re-added).
        # Wait 5s before reverting — if master comes back, cancel the revert.
        self._master_idle_timer = None

        # Settings watcher tracks previous slave config to detect changes
        self._prev_slave_enabled = False
        self._prev_slave_host = ""

    # ─────────────────────────────────────────────────────────────────────────
    # Settings
    # ─────────────────────────────────────────────────────────────────────────

    def _load_settings(self) -> dict:
        try:
            with open(SETTINGS_FILE) as f:
                settings = json.load(f)
            with self._settings_lock:
                self._settings = settings
            return settings
        except Exception as e:
            log(f"Failed to load settings: {e}")
            return {}

    def _get_auto_switch(self) -> dict:
        with self._settings_lock:
            return self._settings.get("autoSwitch", {
                "localActivity": True,
                "slave": {"enabled": False, "masterHost": "",
                          "masterWsPort": 1780, "masterStreamPort": LOCAL_STREAM_PORT}
            })

    # ─────────────────────────────────────────────────────────────────────────
    # Snapserver helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _get_none_stream_id(self) -> Optional[str]:
        status = self._local_client.get_status()
        if not status:
            return None
        for stream in status.get("server", {}).get("streams", []):
            if stream["id"].startswith("none-"):
                return stream["id"]
        return None

    def _get_idle_groups(self, none_stream_id: str) -> list:
        status = self._local_client.get_status()
        if not status:
            return []
        return [
            g for g in status.get("server", {}).get("groups", [])
            if g.get("stream_id") == none_stream_id
        ]

    def _is_local_idle(self) -> bool:
        """Return True if every local group is on a none-* stream."""
        status = self._local_client.get_status()
        if not status:
            return True
        groups = status.get("server", {}).get("groups", [])
        return not groups or all(
            g.get("stream_id", "").startswith("none-") for g in groups
        )

    def _switch_idle_groups_to_stream(self, stream_id: str):
        none_id = self._get_none_stream_id()
        if not none_id:
            log("No none-stream found — cannot auto-switch groups")
            return
        idle_groups = self._get_idle_groups(none_id)
        if not idle_groups:
            log(f"No idle groups to switch to '{stream_id}'")
            return
        switched = 0
        for group in idle_groups:
            names = [c.get("config", {}).get("name", c["id"])
                     for c in group.get("clients", [])]
            if self._local_client.set_group_stream(group["id"], stream_id):
                log(f"✓ Group ({', '.join(names) or group['id']}) → '{stream_id}'")
                switched += 1
        log(f"Auto-switched {switched}/{len(idle_groups)} idle group(s) to '{stream_id}'")

    # ─────────────────────────────────────────────────────────────────────────
    # Local WebSocket monitor
    # ─────────────────────────────────────────────────────────────────────────

    def _local_on_open(self, ws):
        log("Local snapserver WS connected")
        # Seed known streams so we only react to genuinely NEW streams
        status = self._local_client.get_status()
        if status:
            self._local_known_streams = {
                s["id"] for s in status.get("server", {}).get("streams", [])
                if not s["id"].startswith("none-")
            }
            log(f"Seeded local known streams: {self._local_known_streams or '(none)'}")

    def _local_on_message(self, ws, message):
        try:
            message = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", message)
            data = json.loads(message)
            if data.get("method") == "Server.OnUpdate":
                self._handle_local_server_update(
                    data.get("params", {}).get("server", {}))
        except Exception as e:
            log(f"Local WS message error: {e}")

    def _handle_local_server_update(self, server: dict):
        current = {
            s["id"] for s in server.get("streams", [])
            if not s["id"].startswith("none-")
        }
        new_streams = current - self._local_known_streams
        self._local_known_streams = current

        if not new_streams:
            return

        cfg = self._get_auto_switch()

        for stream_id in new_streams:
            log(f"New local stream: '{stream_id}'")

            # If we were following a master, a local source wins — revert first
            if self._slave_following:
                log(f"Local source started while in slave mode — reverting to local")
                self._revert_to_local()

            # Auto-switch idle groups if localActivity is enabled
            if cfg.get("localActivity", True):
                self._switch_idle_groups_to_stream(stream_id)

    def _local_on_error(self, ws, error):
        log(f"Local WS error: {error}")

    def _local_on_close(self, ws, code, msg):
        log("Local WS closed")

    def _run_local_ws(self):
        while self._local_running:
            try:
                url = f"ws://{SNAPSERVER_HOST}:{SNAPSERVER_HTTP_PORT}/jsonrpc"
                self._local_ws = websocket.WebSocketApp(
                    url,
                    on_open=self._local_on_open,
                    on_message=self._local_on_message,
                    on_error=self._local_on_error,
                    on_close=self._local_on_close,
                )
                self._local_ws.run_forever()
            except Exception as e:
                log(f"Local WS failed: {e}")
            if self._local_running:
                time.sleep(5)

    def _start_local_monitor(self):
        self._local_running = True
        threading.Thread(target=self._run_local_ws, daemon=True).start()
        log("Local monitor started")

    # ─────────────────────────────────────────────────────────────────────────
    # Slave mode
    # ─────────────────────────────────────────────────────────────────────────

    def _slave_on_open(self, ws):
        slave = self._get_auto_switch().get("slave", {})
        log(f"Connected to master at {slave.get('masterHost')}")
        # Check master's current state immediately — follow if it's already playing
        self._evaluate_master_state()

    def _slave_on_message(self, ws, message):
        try:
            message = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", message)
            data = json.loads(message)
            method = data.get("method", "")
            if method == "Server.OnUpdate":
                self._handle_master_server_update(
                    data.get("params", {}).get("server", {}))
            elif method == "Group.OnStreamChanged":
                # Single-group update — re-evaluate full master state
                self._evaluate_master_state()
        except Exception as e:
            log(f"Slave WS message error: {e}")

    def _handle_master_server_update(self, server: dict):
        groups = server.get("groups", [])
        if not groups:
            return
        master_active = any(
            not g.get("stream_id", "").startswith("none-") for g in groups
        )
        self._react_to_master_activity(master_active)

    def _evaluate_master_state(self):
        """Query master HTTP status and react.

        Uses regex to extract stream_ids from the raw response instead of
        full JSON parsing. The master's Server.GetStatus response can contain
        binary cover art data in stream metadata properties that makes the JSON
        structurally invalid (unescaped quote bytes). Regex on the raw response
        is immune to this since stream_id only appears in group objects (not
        in stream metadata property values).
        """
        slave = self._get_auto_switch().get("slave", {})
        master_host = slave.get("masterHost", "")
        if not master_host:
            return
        try:
            conn = http.client.HTTPConnection(master_host, SNAPSERVER_HTTP_PORT, timeout=5)
            conn.request("POST", "/jsonrpc",
                         json.dumps({"jsonrpc": "2.0", "id": 1, "method": "Server.GetStatus"}),
                         {"Content-Type": "application/json"})
            response = conn.getresponse()
            raw = response.read().decode("utf-8", errors="replace")
            conn.close()
            # Extract only group stream_id values — these never contain binary data
            stream_ids = re.findall(r'"stream_id"\s*:\s*"([^"]*)"', raw)
            if not stream_ids:
                return
            master_active = any(not sid.startswith("none-") for sid in stream_ids)
            self._react_to_master_activity(master_active)
        except Exception as e:
            log(f"Failed to evaluate master state: {e}")

    def _react_to_master_activity(self, master_active: bool):
        if master_active:
            # Master came back — cancel any pending idle revert
            if self._master_idle_timer:
                self._master_idle_timer.cancel()
                self._master_idle_timer = None
                log("Master active again — cancelled idle revert timer (was a track change)")
            if not self._slave_following and self._is_local_idle():
                log("Master is active — switching snapclient to master")
                self._switch_to_master()
            elif not self._slave_following:
                log("Master is active but local is not idle — not following")
        elif not master_active and self._slave_following:
            # Master appears idle — could be a track change (stream briefly removed).
            # Wait 5s before reverting so seamless track changes don't trigger a restart.
            if self._master_idle_timer is None:
                log("Master appears idle — waiting 5s before reverting (track change guard)")
                self._master_idle_timer = threading.Timer(5.0, self._idle_revert_confirmed)
                self._master_idle_timer.daemon = True
                self._master_idle_timer.start()

    def _idle_revert_confirmed(self):
        """Called 5s after master went idle — reverts if still following."""
        self._master_idle_timer = None
        if self._slave_following:
            log("Master idle confirmed after 5s — reverting snapclient to local")
            self._revert_to_local()

    def _slave_on_error(self, ws, error):
        log(f"Slave WS error: {error}")

    def _slave_on_close(self, ws, code, msg):
        log("Slave WS closed")
        if self._slave_following:
            log("Lost master connection while following — reverting to local")
            self._revert_to_local()

    def _switch_to_master(self):
        slave = self._get_auto_switch().get("slave", {})
        master_host = slave.get("masterHost", "")
        master_port = slave.get("masterStreamPort", LOCAL_STREAM_PORT)
        if not master_host:
            return
        target = f"{master_host}:{master_port}"
        log(f"Writing snapclient target: {target}")
        try:
            with open(SNAPCLIENT_TARGET_FILE, "w") as f:
                f.write(target)
            self._slave_following = True
            self._restart_snapclient()
        except Exception as e:
            log(f"Failed to switch to master: {e}")

    def _revert_to_local(self):
        if not self._slave_following:
            return
        if self._master_idle_timer:
            self._master_idle_timer.cancel()
            self._master_idle_timer = None
        log(f"Writing snapclient target: {SNAPSERVER_HOST}:{LOCAL_STREAM_PORT}")
        try:
            with open(SNAPCLIENT_TARGET_FILE, "w") as f:
                f.write(f"{SNAPSERVER_HOST}:{LOCAL_STREAM_PORT}")
            self._slave_following = False
            self._restart_snapclient()
        except Exception as e:
            log(f"Failed to revert to local: {e}")

    def _restart_snapclient(self):
        try:
            result = subprocess.run(
                ["supervisorctl", "-c", SUPERVISORD_CONF, "restart", "snapclient"],
                capture_output=True, text=True, timeout=30
            )
            log(f"snapclient restarted ({result.returncode})")
        except Exception as e:
            log(f"Failed to restart snapclient: {e}")

    def _run_slave_ws(self, master_host: str, master_ws_port: int):
        while self._slave_running:
            try:
                url = f"ws://{master_host}:{master_ws_port}/jsonrpc"
                self._slave_ws = websocket.WebSocketApp(
                    url,
                    on_open=self._slave_on_open,
                    on_message=self._slave_on_message,
                    on_error=self._slave_on_error,
                    on_close=self._slave_on_close,
                )
                self._slave_ws.run_forever()
            except Exception as e:
                log(f"Slave WS failed: {e}")
            if self._slave_running:
                if self._slave_following:
                    self._revert_to_local()
                time.sleep(10)

    def _start_slave_monitor(self, master_host: str, master_ws_port: int):
        self._slave_running = True
        threading.Thread(
            target=self._run_slave_ws,
            args=(master_host, master_ws_port),
            daemon=True,
        ).start()
        log(f"Slave monitor started → {master_host}:{master_ws_port}")

    def _stop_slave_monitor(self):
        self._slave_running = False
        if self._master_idle_timer:
            self._master_idle_timer.cancel()
            self._master_idle_timer = None
        if self._slave_ws:
            try:
                self._slave_ws.close()
            except Exception:
                pass
        if self._slave_following:
            self._revert_to_local()

    # ─────────────────────────────────────────────────────────────────────────
    # Settings watcher
    # ─────────────────────────────────────────────────────────────────────────

    def _settings_watcher(self):
        while True:
            time.sleep(30)
            try:
                settings = self._load_settings()
                slave = settings.get("autoSwitch", {}).get("slave", {})
                slave_enabled = slave.get("enabled", False)
                slave_host = slave.get("masterHost", "")
                slave_ws_port = slave.get("masterWsPort", 1780)

                config_changed = (
                    slave_enabled != self._prev_slave_enabled
                    or slave_host != self._prev_slave_host
                )
                if config_changed:
                    log(f"Slave config changed: enabled={slave_enabled} host={slave_host!r}")
                    if self._slave_running:
                        self._stop_slave_monitor()
                    if slave_enabled and slave_host:
                        self._start_slave_monitor(slave_host, slave_ws_port)
                    self._prev_slave_enabled = slave_enabled
                    self._prev_slave_host = slave_host
            except Exception as e:
                log(f"Settings watcher error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Entry point
    # ─────────────────────────────────────────────────────────────────────────

    def run(self):
        log("Auto-switch service starting")

        # Wait for snapserver
        log("Waiting for local snapserver...")
        for _ in range(30):
            if self._local_client.get_status():
                break
            time.sleep(2)
        else:
            log("Snapserver not ready after 60s — continuing anyway")

        settings = self._load_settings()
        auto_switch = settings.get("autoSwitch", {})

        # Start local monitor
        self._start_local_monitor()

        # Start slave monitor if configured
        slave = auto_switch.get("slave", {})
        self._prev_slave_enabled = slave.get("enabled", False)
        self._prev_slave_host = slave.get("masterHost", "")
        if self._prev_slave_enabled and self._prev_slave_host:
            self._start_slave_monitor(
                self._prev_slave_host,
                slave.get("masterWsPort", 1780),
            )

        # Start settings watcher
        threading.Thread(target=self._settings_watcher, daemon=True).start()

        log("Auto-switch service running")
        while True:
            time.sleep(60)


if __name__ == "__main__":
    service = AutoSwitchService()
    service.run()
