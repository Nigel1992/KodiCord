import os
import sys
import time
import re
import json as _json
try:
    from urllib.parse import quote as urllib_quote, unquote as urllib_unquote, urlparse
    import urllib.request
    import urllib.error
except Exception:
    try:
        from urllib import quote as urllib_quote
        import urllib2 as urllib_request
        class urllib_error:
            URLError = Exception
            HTTPError = Exception
        urllib_request = urllib_request
        urllib_error = urllib_error
    except Exception:
        def urllib_quote(s):
            return s
        class urllib_request:
            @staticmethod
            def Request(*a, **k):
                class R:
                    pass
                return R()
            @staticmethod
            def urlopen(*a, **k):
                raise Exception("no urllib")
        class urllib_error:
            URLError = Exception
            HTTPError = Exception

_ITUNES_CACHE = {}

import xbmc
import xbmcaddon
import xbmcgui

addon = xbmcaddon.Addon()
ADDON_PATH = addon.getAddonInfo("path")
LIB_PATH = os.path.join(ADDON_PATH, "resources", "lib")
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

from discord_ipc import DiscordIPC, DiscordIPCError
from remote_client import RemoteBridgeClient


def log(msg, level=xbmc.LOGINFO):
    try:
        xbmc.log("[KodiCord] %s" % msg, level)
    except Exception:
        print("[KodiCord] %s" % msg)


def s(key, default=""):
    try:
        v = addon.getSetting(key)
        return v if v is not None else default
    except Exception:
        return default


def sb(key, default=False):
    try:
        return addon.getSettingBool(key)
    except Exception:
        val = s(key, "false").lower()
        return val in ("true", "1", "yes")


player = xbmc.Player()

_play_state = {"value": "stopped"}
_LAST_SOURCE_ADDON = {"v": ""}


def _capture_source_addon():
    global _LAST_SOURCE_ADDON
    for label in ("Player.FilenameAndPath", "Container.FolderPath", "ListItem.Path", "ListItem.FolderPath"):
        try:
            v = xbmc.getInfoLabel(label) or ""
        except Exception:
            v = ""
        if v.startswith("plugin://"):
            parts = v[len("plugin://"):].split("/", 1)
            if parts and parts[0].strip():
                _LAST_SOURCE_ADDON["v"] = parts[0].strip()
                return


def _addon_from_context():
    return (_LAST_SOURCE_ADDON.get("v") or "").strip()
_update_requested = {"v": True}

class _KodiMonitor(xbmc.Monitor):
    def onPlayBackStarted(self):
        _play_state["value"] = "playing"
        _update_requested["v"] = True

    def onPlayBackPaused(self):
        _play_state["value"] = "paused"
        _update_requested["v"] = True

    def onPlayBackResumed(self):
        _play_state["value"] = "playing"
        _update_requested["v"] = True

    def onPlayBackEnded(self):
        _play_state["value"] = "stopped"
        _update_requested["v"] = True

    def onPlayBackStopped(self):
        _play_state["value"] = "stopped"
        _update_requested["v"] = True

monitor = _KodiMonitor()

_discord = {"obj": None}
_remote = {"obj": None}
_last_signature = {"v": None}
_cleared = {"v": False}


def is_remote_mode():
    mode = (s("mode", "0") or "").strip().lower()
    if mode in ("1", "remote", "remote bridge", "remote bridge (pc)"):
        return True
    return "remote" in mode


def client_id():
    v = s("client_id", "").strip()
    return v if v else "123456789012345678"


def ensure_local():
    global _discord
    d = _discord["obj"]
    if d is not None and getattr(d, "connected", False):
        return d
    try:
        if d is not None:
            try:
                d.close()
            except Exception:
                pass
        d = DiscordIPC(client_id())
        d.connect(timeout=5)
        _discord["obj"] = d
        log("Connected to local Discord IPC")
        return d
    except Exception as e:
        log("Local Discord connect failed: %s" % e, xbmc.LOGWARNING)
        _discord["obj"] = None
        return None


def get_remote():
    host = s("remote_host", "127.0.0.1")
    port = s("remote_port", "8765")
    token = s("remote_token", "")
    timeout = s("remote_timeout", "5")
    try:
        port = int(port)
    except Exception:
        port = 8765
    try:
        timeout = int(timeout)
    except Exception:
        timeout = 5
    return RemoteBridgeClient(host, port, token, timeout)


_PAUSED_CACHE = {"last_time": None, "last_ts": 0.0, "paused": False}

def cond_visibility(expr):
    try:
        return bool(xbmc.getCondVisibility(expr))
    except Exception:
        return False

def _active_players():
    """Return the JSON-RPC Player.GetActivePlayers list, or None if unavailable."""
    try:
        resp = xbmc.executeJSONRPC(_json.dumps({
            "jsonrpc": "2.0", "method": "Player.GetActivePlayers", "id": 1
        }))
        data = _json.loads(resp)
        if isinstance(data, dict) and "result" in data:
            return data.get("result") or []
    except Exception:
        pass
    return None


def media_active():
    players = _active_players()
    if players is not None:
        if players:
            if _play_state["value"] == "stopped":
                _play_state["value"] = "playing"
            return True
        # no active player -> nothing is playing, do not trust stale state
        _play_state["value"] = "stopped"
        return False
    # JSON-RPC unavailable: fall back to monitor callbacks
    if _play_state["value"] in ("playing", "paused"):
        return True
    try:
        return bool(player.getPlayingFile()) and bool(player.isPlaying())
    except Exception:
        return False

def is_playing():
    return _play_state["value"] == "playing"

def is_paused():
    if _play_state["value"] == "paused":
        return True
    # fallback stalled time detection
    try:
        t = float(player.getTime() or 0.0)
    except Exception:
        t = 0.0
    now = time.time()
    last_t = _PAUSED_CACHE["last_time"]
    last_ts = _PAUSED_CACHE["last_ts"]
    paused = False
    if last_t is not None and abs(t - last_t) < 0.05 and (now - last_ts) >= 2.0:
        paused = True
    _PAUSED_CACHE["last_time"] = t
    _PAUSED_CACHE["last_ts"] = now
    return paused


def get_itunes_cover(artist, title):
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not artist and not title:
        return "kodi"
    key = "%s-%s" % (artist, title)
    if key in _ITUNES_CACHE:
        return _ITUNES_CACHE[key]
    try:
        term = "%s %s" % (artist, title) if artist and title else (title or artist)
        url = "https://itunes.apple.com/search?term=%s&entity=song&limit=1" % urllib_quote(term)
        req = urllib.request.Request(url, headers={"User-Agent": "KodiCord/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode("utf-8", "replace"))
        results = data.get("results") or []
        if not results:
            _ITUNES_CACHE[key] = "kodi"
            return "kodi"
        arturl = results[0].get("artworkUrl100")
        if not arturl:
            _ITUNES_CACHE[key] = "kodi"
            return "kodi"
        arturl = arturl.replace("100x100bb.jpg", "600x600bb.jpg").replace("100x100", "600x600")
        _ITUNES_CACHE[key] = arturl
        return arturl
    except Exception as e:
        try:
            xbmc.log("[KodiCord] itunes err: %s" % e, xbmc.LOGINFO)
        except Exception:
            pass
        _ITUNES_CACHE[key] = "kodi"
        return "kodi"


def _active_player_id():
    try:
        resp = xbmc.executeJSONRPC(_json.dumps({
            "jsonrpc": "2.0", "method": "Player.GetActivePlayers", "id": 1
        }))
        data = _json.loads(resp)
        players = data.get("result") or []
        if players:
            return players[0].get("playerid", 0)
    except Exception:
        pass
    return 0


def get_art_via_jsonrpc():
    pid = _active_player_id()
    try:
        resp = xbmc.executeJSONRPC(_json.dumps({
            "jsonrpc": "2.0",
            "method": "Player.GetItem",
            "params": {"playerid": pid, "properties": ["art", "thumbnail", "fanart"]},
            "id": 1
        }))
        data = _json.loads(resp)
        item = (data.get("result") or {}).get("item") or {}
        art = item.get("art")
        candidates = []
        if isinstance(art, dict):
            for key in ("thumbnail", "thumb", "poster", "fanart", "icon", "clearlogo", "banner"):
                if art.get(key):
                    candidates.append(art.get(key))
        if item.get("thumbnail"):
            candidates.append(item.get("thumbnail"))
        if item.get("fanart"):
            candidates.append(item.get("fanart"))
        for c in candidates:
            if isinstance(c, str) and c.strip():
                v = c.strip()
                # decode image:// wrappers
                if v.startswith("image://"):
                    v = v[len("image://"):]
                    if v.endswith("/"):
                        v = v[:-1]
                    try:
                        v = urllib_unquote(v)
                    except Exception:
                        pass
                if v.startswith("http://") or v.startswith("https://"):
                    return v
                if v and "ytimg.com" in v:
                    return v
        # if nothing usable, return first candidate decoded
        if candidates:
            v = candidates[0].strip()
            if v.startswith("image://"):
                v = v[len("image://"):]
                if v.endswith("/"):
                    v = v[:-1]
                try:
                    v = urllib.parse.unquote(v)
                except Exception:
                    pass
            return v
    except Exception as e:
        try:
            xbmc.log("[KodiCord] jsonrpc art err: %s" % e, xbmc.LOGINFO)
        except Exception:
            pass
    return ""


def now_playing_info():
    info = {
        "type": None,
        "title": "",
        "subtitle": "",
        "artist": "",
        "album": "",
        "total": 0.0,
        "elapsed": 0.0,
        "file": "",
        "art": "",
        "addon": "",
    }
    try:
        info["file"] = player.getPlayingFile() or ""
    except Exception:
        pass
    # detect source addon from the playing item
    try:
        fap = xbmc.getInfoLabel("Player.FilenameAndPath") or ""
        info["addon"] = ""
        if fap.startswith("plugin://"):
            parts = fap[len("plugin://"):].split("/", 1)
            if parts and parts[0].strip():
                info["addon"] = parts[0].strip()
        elif info.get("file", "").startswith("http") and not info["addon"]:
            # direct stream: fall back to last browsed addon (if any)
            info["addon"] = _addon_from_context()
    except Exception:
        info["addon"] = "" or _addon_from_context()
    try:
        info["total"] = float(player.getTotalTime() or 0.0)
    except Exception:
        pass
    try:
        info["elapsed"] = float(player.getTime() or 0.0)
    except Exception:
        pass

    # video
    try:
        vit = player.getVideoInfoTag()
        title = (vit.getTitle() or "").strip()
        show = (vit.getTVShowTitle() or "").strip()
        season = 0
        episode = 0
        try:
            season = int(vit.getSeason() or 0)
        except Exception:
            season = 0
        try:
            episode = int(vit.getEpisode() or 0)
        except Exception:
            episode = 0
        year = 0
        try:
            year = int(vit.getYear() or 0)
        except Exception:
            year = 0
        if show:
            info["type"] = "video"
            info["title"] = show
            ep_title = title
            if season > 0 or episode > 0:
                parts = []
                if season > 0:
                    parts.append("S%02d" % season)
                if episode > 0:
                    parts.append("E%02d" % episode)
                prefix = "".join(parts)
                if ep_title:
                    info["subtitle"] = "%s - %s" % (prefix, ep_title) if prefix else ep_title
                else:
                    info["subtitle"] = prefix
            elif ep_title:
                info["subtitle"] = ep_title
            if year and not info["subtitle"]:
                info["subtitle"] = str(year)
        elif title:
            info["type"] = "video"
            info["title"] = title
            if year:
                info["subtitle"] = str(year)
    except Exception:
        pass

    # artwork (video)
    if info["type"] == "video":
        try:
            vit = player.getVideoInfoTag()
            for key in ("thumb", "poster", "fanart", "clearlogo", "banner"):
                try:
                    val = vit.getArt(key)
                except Exception:
                    continue
                if val:
                    info["art"] = val
                    break
        except Exception:
            pass

    # music
    try:
        mit = player.getMusicInfoTag()
        mtitle = (mit.getTitle() or "").strip()
        artist = ""
        try:
            a = mit.getArtist()
            if isinstance(a, (list, tuple)):
                artist = ", ".join([str(x) for x in a if x])
            else:
                artist = str(a or "")
        except Exception:
            artist = ""
        album = ""
        try:
            album = str(mit.getAlbum() or "")
        except Exception:
            album = ""
        if mtitle:
            # trust the music tag for audio playback
            info["type"] = "music"
            info["title"] = mtitle
            bits = [b for b in (artist, album) if b.strip()]
            info["subtitle"] = " - ".join(bits)
            info["artist"] = artist
            info["album"] = album
        elif artist and not info["title"]:
            info["type"] = "music"
            info["artist"] = artist
            info["album"] = album
        # iTunes cover
        if (mtitle or info.get("title")):
            try:
                it_art = get_itunes_cover(artist, mtitle or info.get("title") or "")
                if it_art and it_art != "kodi":
                    info["art"] = it_art
            except Exception:
                pass
        # artwork (music) fallback
        if not info["art"]:
            try:
                a = mit.getArt()
                if isinstance(a, dict):
                    for k, v in a.items():
                        if v and not info["art"]:
                            info["art"] = v
                elif isinstance(a, str) and a:
                    info["art"] = a
            except Exception:
                pass
            if not info["art"]:
                for key in ("thumb", "album.thumb", "fanart", "clearlogo", "poster", "banner"):
                    try:
                        val = mit.getArt(key)
                        if val:
                            if not info["art"]:
                                info["art"] = val
                    except Exception:
                        pass
    except Exception:
        pass

    # fallback artwork from player
    if not info["art"]:
        try:
            for key in ("thumb", "poster", "fanart"):
                try:
                    val = player.getArt(key)
                    if val:
                        info["art"] = val
                        break
                except Exception:
                    pass
        except Exception:
            pass

    # fallback artwork via Kodi JSON-RPC
    if not info["art"]:
        try:
            info["art"] = get_art_via_jsonrpc()
        except Exception:
            pass
    # YouTube thumbnail fallback
    if not info["art"] and info.get("type") == "video":
        try:
            f = info.get("file") or ""
            m = re.search(r"(?:video_id=|/vi/|[?&]v=)([A-Za-z0-9_-]{11})", f)
            if m:
                info["art"] = "https://i.ytimg.com/vi/%s/hqdefault.jpg" % m.group(1)
        except Exception:
            pass
    # try iTunes if still nothing for music
    if not info["art"] and info.get("type") == "music":
        try:
            artist = ""
            sub = info.get("subtitle") or ""
            if "-" in sub:
                artist = sub.split("-", 1)[0].strip()
            title = info.get("title") or ""
            if not title:
                # try filename
                if info.get("file"):
                    base = os.path.basename(info["file"])
                    name, _ = os.path.splitext(base)
                    # strip track number prefix
                    name = name.strip()
                    title = name
            for qterm in ("%s %s" % (artist, title), title, artist):
                if not qterm.strip():
                    continue
                term = urllib_quote(qterm)
                url = "https://itunes.apple.com/search?term=%s&entity=song&limit=5" % term
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "KodiCord/1.0"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        raw = resp.read()
                        data = _json.loads(raw.decode("utf-8", "replace"))
                except Exception as e:
                    xbmc.log("[KodiCord] itunes req err: %s" % e, xbmc.LOGINFO)
                    continue
                results = data.get("results") or []
                if results:
                    r = results[0]
                    arturl = r.get("artworkUrl100") or r.get("artworkUrl60") or r.get("artworkUrl30")
                    if arturl:
                        arturl = arturl.replace("100x100", "600x600").replace("60x60", "600x600").replace("30x30", "600x600")
                        info["art"] = arturl
                        break
        except Exception as e:
            try:
                xbmc.log("[KodiCord] itunes err: %s" % e, xbmc.LOGINFO)
            except Exception:
                pass

    # fallback to filename
    audio_exts = (".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma", ".mpc", ".ape", ".alac")
    if info["file"]:
        ext = os.path.splitext(info["file"])[1].lower()
        if ext in audio_exts:
            info["type"] = "music"
    if (not info["title"] or info.get("type") == "music") and sb("share_filename", True) and info["file"]:
        base = os.path.basename(info["file"])
        name, _ = os.path.splitext(base)
        if name:
            if info.get("type") == "music":
                # common "Artist - Title" or "01. Title" filenames
                clean = re.sub(r"^\s*\d+[\.\-\s]+", "", name).strip()
                if " - " in clean:
                    parts = clean.split(" - ", 1)
                    if not info.get("artist"):
                        info["artist"] = parts[0].strip()
                    if not info["title"]:
                        info["title"] = parts[1].strip()
                elif not info["title"]:
                    info["title"] = clean
                if info.get("artist") and info.get("title") and not info.get("subtitle"):
                    info["subtitle"] = info["artist"]
            elif not info["title"]:
                info["title"] = name
            if info["type"] is None:
                info["type"] = "video"

    if info["type"] is None:
        info["type"] = "video"
    return info


def clear_status():
    log("Clearing presence")
    try:
        if is_remote_mode():
            get_remote().clear()
        else:
            d = _discord["obj"]
            if d is not None:
                try:
                    d.clear()
                except Exception:
                    pass
                try:
                    d.close()
                except Exception:
                    pass
                _discord["obj"] = None
    except Exception as e:
        log("clear failed: %s" % e, xbmc.LOGWARNING)


def update_status():
    global _last_signature, _cleared
    _capture_source_addon()
    if not sb("enabled", True):
        if not _cleared["v"]:
            clear_status()
            _cleared["v"] = True
        return

    _active = media_active()
    _paused_now = is_paused()
    if not _active:
        if sb("clear_on_stop", True) and not _cleared["v"]:
            clear_status()
            _cleared["v"] = True
        _last_signature["v"] = None
        _play_state["value"] = "stopped"
        _PAUSED_CACHE["last_time"] = None
        _PAUSED_CACHE["last_ts"] = 0.0
        return

    _cleared["v"] = False
    info = now_playing_info()
    if not (info.get("title") or info.get("subtitle") or info.get("file")):
        # player is transitioning/stopping and has nothing to report yet
        return
    # blacklist: skip sharing info for selected source addons
    addon_id = (info.get("addon") or "").strip()
    file_path = (info.get("file") or "").strip()
    title = (info.get("title") or "").strip()
    blocked = [x.strip().lower() for x in (s("blacklist_addons", "") or "").split(",") if x.strip()]
    def _is_blocked(value):
        v = (value or "").strip().lower()
        if not v:
            return False
        for b in blocked:
            if not b:
                continue
            if b == v or b in v or v in b:
                return True
        return False
    blocked_hit = False
    if addon_id and _is_blocked(addon_id):
        blocked_hit = True
    elif not addon_id:
        # fall back to matching against the playing path/title when no addon id was detected
        for val in (file_path, title):
            if _is_blocked(val):
                blocked_hit = True
                break
    if blocked_hit:
        if sb("clear_on_stop", True) and not _cleared["v"]:
            clear_status()
            _cleared["v"] = True
        _last_signature["v"] = None
        return
    paused = _paused_now
    sig = (info["type"], info["title"], info["subtitle"], paused, info.get("art", ""))
    if sig == _last_signature["v"]:
        # nothing changed; skip to reduce traffic
        return
    _last_signature["v"] = sig

    media_type = info.get("type") or "video"
    if media_type not in ("music", "video"):
        media_type = "video"
    title = info.get("title") or ""
    artist = info.get("artist") or ""
    album = info.get("album") or ""
    subtitle = info.get("subtitle") or ""
    thumbnail = info.get("art") or ""
    media_url = info.get("file") or ""
    total = info.get("total") or 0.0
    elapsed = info.get("elapsed") or 0.0
    privacy = s("privacy_mode", "0")
    show_ts = sb("show_timestamps", True)

    # presence title override (top line of the Discord card)
    presence_mode = (s("presence_name_mode", "1") or "1").strip().lower()
    if presence_mode in ("1", "media title", "title"):
        if media_type == "music":
            if artist and title:
                activity_name = "%s - %s" % (artist, title)
            else:
                activity_name = title or artist or None
        else:
            activity_name = title or None
    elif presence_mode in ("2", "media", "media type on kodi"):
        activity_name = "music on Kodi" if media_type == "music" else "a video on Kodi"
    elif presence_mode in ("3", "custom"):
        activity_name = (s("presence_custom_name", "") or "").strip() or None
    else:
        activity_name = None
    log("Updating presence: %s / %s (%s) [addon=%s]" % (media_type, title or subtitle, "paused" if paused else "playing", info.get("addon") or "-"))

    try:
        if is_remote_mode():
            ok = get_remote().update_activity(
                media_type=media_type, title=title, artist=artist, album=album,
                subtitle=subtitle, thumbnail=thumbnail, media_url=media_url,
                paused=paused, privacy_mode=privacy, show_timestamps=show_ts,
                total=total, elapsed=elapsed, activity_name=activity_name
            )
            if not ok:
                log("Remote bridge update failed", xbmc.LOGWARNING)
        else:
            d = ensure_local()
            if d is None:
                return
            d.update_activity(
                media_type=media_type, title=title, artist=artist, album=album,
                subtitle=subtitle, thumbnail=thumbnail, media_url=media_url,
                paused=paused, privacy_mode=privacy, show_timestamps=show_ts,
                total=total, elapsed=elapsed, activity_name=activity_name
            )
    except Exception as e:
        log("update failed: %s" % e, xbmc.LOGWARNING)
        # reset local connection
        if not is_remote_mode():
            try:
                if _discord["obj"] is not None:
                    _discord["obj"].close()
            except Exception:
                pass
            _discord["obj"] = None


def main():
    log("KodiCord service started")
    # initial delay to let Kodi settle
    if monitor.waitForAbort(3):
        return
    try:
        if player.getPlayingFile():
            _play_state["value"] = "playing"
            _update_requested["v"] = True
    except Exception:
        pass
    while not monitor.abortRequested():
        try:
            update_status()
        except Exception as e:
            log("loop error: %s" % e, xbmc.LOGERROR)
        interval = 5
        try:
            interval = int(s("update_interval", "5"))
        except Exception:
            interval = 5
        if interval < 2:
            interval = 2
        if monitor.waitForAbort(interval):
            break
    # cleanup
    clear_status()
    log("KodiCord service stopped")


if __name__ == "__main__":
    main()