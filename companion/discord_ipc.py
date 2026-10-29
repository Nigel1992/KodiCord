"""Pure-Python client for the Discord Rich Presence IPC socket.

Works without any third-party dependencies. Supports Linux/macOS (Unix
sockets) and Windows (named pipes). Only a single Discord client instance
is contacted (discord-ipc-0 .. discord-ipc-9).
"""

import json
import os
import socket
import struct
import sys
import time
import uuid
import re

try:
    import urllib.request as urllib_request
except Exception:
    urllib_request = None

try:
    from urllib.parse import quote as urllib_quote, unquote as urllib_unquote
except Exception:
    try:
        from urllib import quote as urllib_quote, unquote as urllib_unquote
    except Exception:
        def urllib_quote(s):
            return s
        def urllib_unquote(s):
            return s


class DiscordIPCError(Exception):
    pass


class DiscordIPC:
    OP_HANDSHAKE = 0
    OP_FRAME = 1
    OP_CLOSE = 2
    OP_PING = 3
    OP_PONG = 4

    def __init__(self, client_id):
        self.client_id = str(client_id)
        self.sock = None          # unix socket
        self.pipe = None          # windows named pipe file object
        self._connected = False
        self.last_response = None

    # ------------------------------------------------------------------ #
    # connection
    # ------------------------------------------------------------------ #
    def connect(self, timeout=5):
        if sys.platform == "win32":
            self._connect_windows()
        else:
            self._connect_unix()
        if not self._connected:
            raise DiscordIPCError("Could not find a running Discord IPC socket")
        # handshake
        self._send(self.OP_HANDSHAKE, {"v": 1, "client_id": self.client_id})
        # wait for READY (best effort)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                op, payload = self._recv(timeout=1)
            except Exception:
                break
            if isinstance(payload, dict) and payload.get("cmd") == "DISPATCH" and payload.get("evt") == "READY":
                return True
            if isinstance(payload, dict) and payload.get("evt") == "READY":
                return True
        return True

    def _connect_unix(self):
        uid = None
        try:
            uid = os.getuid()
        except AttributeError:
            uid = None
        home = os.path.expanduser("~")
        candidates = []
        for i in range(10):
            if uid is not None:
                candidates.append("/run/user/%d/discord-ipc-%d" % (uid, i))
            candidates.append("/tmp/discord-ipc-%d" % i)
        for app in ("discord", "Discord", "discordcanary", "discordptb",
                    "discorddevelopment", "discord-canary", "discord-ptb"):
            for i in range(10):
                candidates.append(os.path.join(home, ".config", app, "discord-ipc-%d" % i))
        # environment override
        env_path = os.environ.get("DISCORD_IPC_PATH")
        if env_path:
            candidates.insert(0, env_path)

        for path in candidates:
            if not os.path.exists(path):
                continue
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(5)
                s.connect(path)
                self.sock = s
                self._connected = True
                return
            except Exception:
                try:
                    s.close()
                except Exception:
                    pass
        self._connected = False

    def _connect_windows(self):
        for i in range(10):
            path = r"\\.\pipe\discord-ipc-%d" % i
            try:
                f = open(path, "r+b", buffering=0)
                self.pipe = f
                self._connected = True
                return
            except Exception:
                continue
        self._connected = False

    # ------------------------------------------------------------------ #
    # io helpers
    # ------------------------------------------------------------------ #
    def _send(self, opcode, payload):
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header = struct.pack("<II", opcode, len(data))
        blob = header + data
        if self.sock is not None:
            self.sock.sendall(blob)
        elif self.pipe is not None:
            self.pipe.write(blob)
            self.pipe.flush()
        else:
            raise DiscordIPCError("not connected")

    def _recv_exact(self, n, timeout=5):
        buf = b""
        if self.sock is not None:
            self.sock.settimeout(timeout)
            while len(buf) < n:
                chunk = self.sock.recv(n - len(buf))
                if not chunk:
                    raise DiscordIPCError("socket closed")
                buf += chunk
            return buf
        if self.pipe is not None:
            self.pipe.timeout = timeout  # not standard, ignore
            deadline = time.time() + timeout
            while len(buf) < n and time.time() < deadline:
                try:
                    chunk = self.pipe.read(n - len(buf))
                except Exception:
                    chunk = b""
                if not chunk:
                    time.sleep(0.05)
                    continue
                buf += chunk
            if len(buf) < n:
                raise DiscordIPCError("pipe read timeout")
            return buf
        raise DiscordIPCError("not connected")

    def _recv(self, timeout=5):
        header = self._recv_exact(8, timeout=timeout)
        op, length = struct.unpack("<II", header)
        if length == 0:
            return op, {}
        payload_raw = self._recv_exact(length, timeout=timeout)
        try:
            payload = json.loads(payload_raw.decode("utf-8", "replace"))
        except Exception:
            payload = {}
        return op, payload

    # ------------------------------------------------------------------ #
    # public api
    # ------------------------------------------------------------------ #
    def set_activity(self, activity):
        if not self._connected:
            raise DiscordIPCError("not connected")
        nonce = str(uuid.uuid4())
        args = {"pid": os.getpid()}
        if activity is not None:
            args["activity"] = activity
        else:
            args["activity"] = None
        payload = {"cmd": "SET_ACTIVITY", "args": args, "nonce": nonce}
        self._send(self.OP_FRAME, payload)
        # best-effort read response
        try:
            _op, resp = self._recv(timeout=2)
            self.last_response = resp
        except Exception:
            self.last_response = None

    def clear(self):
        try:
            self.set_activity(None)
        except Exception:
            pass

    def close(self):
        try:
            self._send(self.OP_CLOSE, {})
        except Exception:
            pass
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        if self.pipe is not None:
            try:
                self.pipe.close()
            except Exception:
                pass
            self.pipe = None
        self._connected = False

    @property
    def connected(self):
        return self._connected


# ---------------------------------------------------------------------- #
# Activity helpers
# ---------------------------------------------------------------------- #
_APP_NAME_CACHE = {"id": None, "name": None, "ts": 0.0}


def get_application_name(client_id, timeout=4, ttl=3600):
    """Return the Discord application name for client_id.

    Discord caches application names in the desktop client, so a renamed app
    can keep showing its old name. Sending the current name in the activity
    payload avoids that stale cache. Results are cached locally for an hour.
    """
    cid = str(client_id or "").strip()
    if not cid or urllib_request is None:
        return None
    now = time.time()
    if _APP_NAME_CACHE["id"] == cid and (now - _APP_NAME_CACHE["ts"]) < ttl:
        return _APP_NAME_CACHE["name"]
    name = None
    try:
        url = "https://discord.com/api/v10/applications/%s/rpc" % urllib_quote(cid)
        req = urllib_request.Request(url, headers={"User-Agent": "KodiCord/1.0"})
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        value = data.get("name")
        if isinstance(value, str) and value.strip():
            name = value.strip()
    except Exception:
        name = None
    _APP_NAME_CACHE.update({"id": cid, "name": name, "ts": now})
    return name


def _decode_image_url(url):
    url = (url or "").strip()
    if url.startswith("image://"):
        v = url[len("image://"):]
        if v.endswith("/"):
            v = v[:-1]
        try:
            v = urllib_unquote(v)
        except Exception:
            pass
        url = v
    return url


def resolve_thumbnail(thumbnail=None, media_url=None):
    url = _decode_image_url(thumbnail)
    if url.startswith("http://") or url.startswith("https://"):
        return url
    source = media_url or ""
    m = re.search(r"(?:video_id=|/vi/|[?&]v=)([A-Za-z0-9_-]{11})", source)
    if m:
        return "https://i.ytimg.com/vi/%s/hqdefault.jpg" % m.group(1)
    if isinstance(media_url, str) and (media_url.startswith("http://") or media_url.startswith("https://")):
        return media_url
    return None


def _youtube_id(thumbnail=None, media_url=None):
    for src in (thumbnail, media_url):
        if not isinstance(src, str):
            continue
        m = re.search(r"ytimg\.com/vi/([A-Za-z0-9_-]{11})", src)
        if m:
            return m.group(1)
        m = re.search(r"(?:video_id=|/vi/|[?&]v=|file=)([A-Za-z0-9_-]{11})", src)
        if m:
            return m.group(1)
    if isinstance(media_url, str):
        base = os.path.basename(media_url)
        m = re.search(r"([A-Za-z0-9_-]{11})", base)
        if m:
            return m.group(1)
    return None


MUSICLINK_API_KEY = "st_3bc3b4cee303e096e385efa1df91cd6ad2f12bbd9cb73a31"

_ITUNES_LINK_CACHE = {}
_MUSICLINK_CACHE = {}


def get_itunes_track_url(artist=None, title=None, timeout=5, ttl=86400):
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not artist and not title:
        return None
    key = "%s-%s" % (artist, title)
    now = time.time()
    cached = _ITUNES_LINK_CACHE.get(key)
    if isinstance(cached, tuple):
        ts, value = cached
        if (now - ts) < ttl:
            return value
    url = None
    try:
        term = "%s %s" % (artist, title) if artist and title else (title or artist)
        api = "https://itunes.apple.com/search?term=%s&entity=song&limit=1" % urllib_quote(term)
        req = urllib_request.Request(api, headers={"User-Agent": "KodiCord/1.0"})
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        results = data.get("results") or []
        if results:
            url = results[0].get("trackViewUrl")
    except Exception:
        url = None
    if not url:
        q = " ".join([x for x in (artist, title) if x]).strip()
        if q:
            url = "https://music.apple.com/search?term=%s" % urllib_quote(q)
    _ITUNES_LINK_CACHE[key] = (now, url)
    return url


def get_music_platform_links(url, timeout=8):
    if not url:
        return (url, {})
    now = time.time()
    cached = _MUSICLINK_CACHE.get(url)
    if cached and (now - cached.get("ts", 0)) < 86400:
        return (cached.get("universal") or url, cached.get("platforms") or {})
    universal = url
    platforms = {}
    try:
        api = "https://api.musiclink.one/v2/resolve?q=%s" % urllib_quote(url)
        req = urllib_request.Request(api, headers={
            "Authorization": "Bearer %s" % MUSICLINK_API_KEY,
            "User-Agent": "KodiCord/1.0",
        })
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        if data.get("success"):
            items = data.get("data") or []
            if items:
                item = items[0]
                universal = item.get("url") or universal
                platforms = item.get("platforms") or {}
    except Exception:
        pass
    _MUSICLINK_CACHE[url] = {"ts": now, "universal": universal, "platforms": platforms}
    return (universal, platforms)


def resolve_link(media_type="music", title=None, artist=None, thumbnail=None, media_url=None):
    is_music = (media_type == "music")
    if is_music:
        itunes_url = get_itunes_track_url(artist, title)
        if itunes_url:
            universal, platforms = get_music_platform_links(itunes_url)
            # open the universal musiclink page (all platforms) when clicked
            return universal or itunes_url
        if isinstance(media_url, str) and ("spotify.com" in media_url or "apple.com" in media_url or "musiclink.one" in media_url):
            return media_url
        q = " ".join([str(x) for x in (artist, title) if x and str(x).strip()]).strip()
        if q:
            return "https://music.apple.com/search?term=%s" % urllib_quote(q)
        return None
    # video
    vid = _youtube_id(thumbnail, media_url)
    if vid:
        return "https://www.youtube.com/watch?v=%s" % vid
    if isinstance(media_url, str) and (media_url.startswith("http://") or media_url.startswith("https://")):
        return media_url
    return None
def build_activity(media_type="music", title=None, artist=None, album=None, subtitle=None,
                   thumbnail=None, media_url=None, paused=False, privacy_mode="0",
                   show_timestamps=True, total=0.0, elapsed=0.0, activity_name=None):
    pm = str(privacy_mode or "0").strip().lower()
    generic = pm in ("2", "generic") or "generic" in pm
    title_only = pm in ("1", "title only") or "title only" in pm

    is_music = (media_type == "music")
    activity_type = 2 if is_music else 3

    if generic:
        details = "Listening to music" if is_music else "Watching a video"
        state = "Kodi"
    else:
        details = title or ("Music" if is_music else "Video")
        if title_only:
            state = "Kodi"
        else:
            if is_music:
                bits = [b for b in (artist, album) if b and str(b).strip()]
                state = " - ".join(bits) if bits else "Kodi"
            else:
                state = subtitle or "Kodi"

    assets = {
        "large_image": "kodi",
        "large_text": "Kodi Media Center",
    }
    thumb_url = resolve_thumbnail(thumbnail, media_url)
    if thumb_url:
        assets["large_image"] = thumb_url

    media_link = resolve_link(media_type, title=title, artist=artist, thumbnail=thumbnail, media_url=media_url)
    if media_link:
        assets["large_url"] = media_link

    activity = {
        "type": activity_type,
        "details": str(details)[:128],
        "state": str(state or "Kodi")[:128],
        "assets": assets,
    }
    if media_link:
        activity["details_url"] = media_link
    if activity_name:
        # overrides the cached Discord application name on the presence card
        activity["name"] = str(activity_name)[:128]
    if media_link:
        if media_type == "music":
            itunes_url = get_itunes_track_url(artist, title)
            universal, platforms = get_music_platform_links(itunes_url) if itunes_url else (media_link, {})
            btns = []
            if platforms.get("spotify"):
                btns.append({"label": "Listen on Spotify", "url": platforms["spotify"][:512]})
            if platforms.get("apple_music"):
                btns.append({"label": "Listen on Apple Music", "url": platforms["apple_music"][:512]})
            if not btns:
                btns.append({"label": "Listen on Apple Music", "url": media_link[:512]})
            activity["buttons"] = btns[:2]
        else:
            activity["buttons"] = [{"label": "Watch on YouTube", "url": media_link[:512]}]

    if show_timestamps and not paused:
        try:
            total = float(total or 0.0)
            elapsed = float(elapsed or 0.0)
        except Exception:
            total = 0.0
            elapsed = 0.0
        if total > 0:
            start = int(time.time() - elapsed)
            activity["timestamps"] = {
                "start": start,
                "end": int(start + total),
            }
        elif elapsed > 0:
            activity["timestamps"] = {"start": int(time.time() - elapsed)}

    if paused:
        st = activity.get("state", "")
        if "paused" not in str(st).lower():
            activity["state"] = ("%s (paused)" % st)[:128]

    return activity


def update_activity(self, media_type="music", title=None, artist=None, album=None,
                    subtitle=None, thumbnail=None, media_url=None, paused=False,
                    privacy_mode="0", show_timestamps=True, total=0.0, elapsed=0.0,
                    clear=False, activity_name=None):
    if clear:
        self.clear()
        return True
    if activity_name is None:
        activity_name = get_application_name(getattr(self, "client_id", None))
    activity = build_activity(
        media_type=media_type, title=title, artist=artist, album=album,
        subtitle=subtitle, thumbnail=thumbnail, media_url=media_url, paused=paused,
        privacy_mode=privacy_mode, show_timestamps=show_timestamps,
        total=total, elapsed=elapsed, activity_name=activity_name
    )
    self.set_activity(activity)
    return True

# attach method to class
DiscordIPC.update_activity = update_activity