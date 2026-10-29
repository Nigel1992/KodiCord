#!/usr/bin/env python3
"""Companion bridge for KodiCord.

Run this on the PC that hosts your Discord client. It exposes a tiny HTTP
API that the Kodi addon talks to, and forwards Rich Presence updates to the
local Discord IPC socket.

Usage:
    python3 discord_bridge.py --client-id 123456789012345678 --port 8765 --token secret
"""

import argparse
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from discord_ipc import DiscordIPC, DiscordIPCError

try:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
except ImportError:  # py2 fallback not expected
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer as ThreadingHTTPServer


class BridgeState:
    def __init__(self, client_id, token=""):
        self.client_id = client_id
        self.token = token
        self.ipc = None
        self.lock = threading.Lock()

    def _connect(self):
        try:
            if self.ipc is not None:
                try:
                    self.ipc.close()
                except Exception:
                    pass
            self.ipc = DiscordIPC(self.client_id)
            self.ipc.connect(timeout=5)
            return True
        except Exception as e:
            self.ipc = None
            print("[bridge] connect failed: %s" % e)
            return False

    def ensure(self):
        with self.lock:
            if self.ipc is not None and self.ipc.connected:
                return True
            return self._connect()

    def update(self, activity):
        if not self.ensure():
            return False
        try:
            with self.lock:
                self.ipc.set_activity(activity)
            return True
        except Exception as e:
            print("[bridge] update failed: %s" % e)
            with self.lock:
                try:
                    if self.ipc is not None:
                        self.ipc.close()
                except Exception:
                    pass
                self.ipc = None
            return False

    def clear(self):
        return self.update(None)


STATE = None


class Handler(BaseHTTPRequestHandler):
    def _auth_ok(self):
        if not STATE.token:
            return True
        return self.headers.get("X-Auth-Token", "") == STATE.token

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/ping":
            if not self._auth_ok():
                self._send_json(401, {"ok": False})
                return
            self._send_json(200, {"ok": True, "connected": STATE.ensure()})
            return
        self._send_json(404, {"ok": False})

    def do_POST(self):
        path = self.path.split("?")[0]
        if not self._auth_ok():
            self._send_json(401, {"ok": False})
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw.decode("utf-8", "replace") or "{}")
        except Exception:
            data = {}
        if path == "/activity":
            if data.get("clear"):
                print("[bridge] clear")
                try:
                    STATE.ipc.clear()
                    ok = True
                except Exception:
                    ok = False
                self._send_json(200 if ok else 503, {"ok": ok})
                return
            if "activity" in data:
                ok = STATE.update(data.get("activity"))
                self._send_json(200 if ok else 503, {"ok": ok})
                return
            # metadata-style request -> use DiscordIPC.update_activity
            print("[bridge] %s | %s | thumb=%s | url=%s" % (
                data.get("media_type"), data.get("title"),
                data.get("thumbnail"), data.get("media_url")))
            try:
                if not STATE.ensure():
                    self._send_json(503, {"ok": False})
                    return
                ok = STATE.ipc.update_activity(**data)
                resp = getattr(STATE.ipc, "last_response", None)
                if isinstance(resp, dict) and resp.get("evt") == "ERROR":
                    print("[bridge] Discord rejected activity: %s" % (resp.get("data"),))
                    ok = False
                self._send_json(200 if ok else 503, {"ok": ok})
            except Exception as e:
                print("[bridge] update_activity failed: %s" % e)
                self._send_json(503, {"ok": False})
            return
        self._send_json(404, {"ok": False})

    def log_message(self, *args):
        # keep console quiet
        pass


def main():
    global STATE
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", default="")
    args = ap.parse_args()

    STATE = BridgeState(args.client_id, args.token)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print("KodiCord bridge listening on %s:%d" % (args.host, args.port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if STATE.ipc is not None:
                STATE.ipc.close()
        except Exception:
            pass
        httpd.server_close()


if __name__ == "__main__":
    main()