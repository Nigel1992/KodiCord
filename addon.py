import os
import sys
import xbmc
import xbmcaddon
import xbmcgui

addon = xbmcaddon.Addon("service.kodicord")
ADDON_PATH = addon.getAddonInfo("path")
LIB_PATH = os.path.join(ADDON_PATH, "resources", "lib")
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

from remote_client import RemoteBridgeClient

dlg = xbmcgui.Dialog()

def manage_blacklist():
    try:
        import json as _json
        payload = {"jsonrpc": "2.0", "method": "Addons.GetAddons",
                   "params": {"properties": ["name"],
                              "limits": {"start": 0, "end": 1000}}, "id": 1}
        resp = _json.loads(xbmc.executeJSONRPC(_json.dumps(payload)))
        addons = (resp.get("result") or {}).get("addons") or []
        # keep media source addons (plugins/scripts/video/audio/image addons), skip builtins
        filtered = []
        for a in addons:
            aid = a.get("addonid") or ""
            typ = (a.get("type") or "").lower()
            if aid.startswith("kodi.") or aid.startswith("xbmc.") or aid.startswith("audioencoder."):
                continue
            if ("plugin" in typ) or typ in ("xbmc.python.script",) or typ.startswith("xbmc.addon."):
                filtered.append(a)
        if not filtered:
            filtered = [a for a in addons if not (a.get("addonid") or "").startswith(("kodi.", "xbmc.", "audioencoder."))]
        seen = set()
        uniq = []
        for a in filtered:
            aid = a.get("addonid")
            if not aid or aid in seen:
                continue
            seen.add(aid)
            uniq.append(a)
        uniq.sort(key=lambda a: (a.get("name") or a.get("addonid") or "").lower())
        items = [a.get("addonid") for a in uniq]
        labels = ["%s  (%s)" % (a.get("name") or a.get("addonid"), a.get("addonid")) for a in uniq]
        current = [x.strip() for x in (addon.getSetting("blacklist_addons") or "").split(",") if x.strip()]
        pre = [i for i, aid in enumerate(items) if aid in current]
        sel = dlg.multiselect("Blacklisted addons", labels, preselect=pre)
        if sel is not None:
            chosen = [items[i] for i in sel]
            addon.setSetting("blacklist_addons", ",".join(chosen))
            dlg.notification("KodiCord", "Blacklist updated (%d)" % len(chosen), xbmcgui.NOTIFICATION_INFO)
    except Exception as e:
        dlg.notification("KodiCord", "Error: %s" % str(e), xbmcgui.NOTIFICATION_ERROR)


def main():
    if any(str(a).strip().lower() == 'blacklist' for a in (sys.argv[1:] or [])):
        manage_blacklist()
        return
    try:
        addon.openSettings()
    except Exception:
        pass
    choice = dlg.select("KodiCord", ["Manage addon blacklist", "Test local Discord connection", "Test remote bridge", "Show current settings", "Open settings", "Exit"])
    if choice == 0:
        manage_blacklist()
        return
    if choice == 1:
        try:
            sys.path.insert(0, LIB_PATH)
            from discord_ipc import DiscordIPC
            d = DiscordIPC(addon.getSetting("client_id"))
            d.connect(timeout=5)
            d.set_activity({"type": 0, "details": "KodiCord test", "state": "Testing connection", "assets": {"large_image": "kodi", "large_text": "Kodi"}})
            xbmc.sleep(2000)
            d.clear()
            d.close()
            dlg.notification("KodiCord", "Local Discord connection OK", xbmcgui.NOTIFICATION_INFO)
        except Exception as e:
            dlg.notification("KodiCord", "Local connection failed: %s" % str(e), xbmcgui.NOTIFICATION_ERROR)
    elif choice == 2:
        try:
            c = RemoteBridgeClient(addon.getSetting("remote_host"), addon.getSetting("remote_port"),
                                   addon.getSetting("remote_token"), addon.getSetting("remote_timeout"))
            if c.ping():
                dlg.notification("KodiCord", "Bridge reachable", xbmcgui.NOTIFICATION_INFO)
            else:
                dlg.notification("KodiCord", "Bridge not reachable", xbmcgui.NOTIFICATION_ERROR)
        except Exception as e:
            dlg.notification("KodiCord", "Error: %s" % str(e), xbmcgui.NOTIFICATION_ERROR)
    elif choice == 3:
        msg = ("Mode: %s\nClient ID: %s\nRemote: %s:%s" %
               (addon.getSetting("mode"), addon.getSetting("client_id"),
                addon.getSetting("remote_host"), addon.getSetting("remote_port")))
        dlg.ok("KodiCord settings", msg)

    elif choice == 4:
        try:
            addon.openSettings()
        except Exception:
            pass
    elif choice == 5:
        return



if __name__ == "__main__":
    main()