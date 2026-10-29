"""HTTP client for the companion Discord bridge running on a PC."""

import json
import urllib.request
import urllib.error


class RemoteBridgeClient:
    def __init__(self, host, port, token="", timeout=5):
        self.host = host.strip()
        self.port = int(port)
        self.token = token or ""
        self.timeout = int(timeout) if timeout else 5

    def _url(self, path):
        return "http://%s:%d%s" % (self.host, self.port, path)

    def _post(self, path, data):
        raw = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(self._url(path), data=raw, method="POST")
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("X-Auth-Token", self.token)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def update(self, activity):
        return self._post("/activity", {"activity": activity})

    def update_activity(self, **kwargs):
        return self._post("/activity", kwargs)

    def clear(self):
        return self._post("/activity", {"clear": True})

    def ping(self):
        try:
            req = urllib.request.Request(self._url("/ping"), method="GET")
            if self.token:
                req.add_header("X-Auth-Token", self.token)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status == 200
        except Exception:
            return False