# 🎬 KodiCord — Discord Rich Presence for Kodi

<img width="300" height="300" alt="image" src="https://github.com/user-attachments/assets/54f387ad-1eb6-4ca2-ba83-3a91c2b0813a" />


[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Kodi](https://img.shields.io/badge/Kodi-19%2B-blue?logo=kodi)](https://kodi.tv)
[![Python](https://img.shields.io/badge/Python-3.x-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Discord](https://img.shields.io/badge/Discord-Rich%20Presence-5865F2?logo=discord&logoColor=white)](https://discord.com/developers/applications)

> Show what you're watching or listening to on Kodi — live, in your Discord status.
> Works **locally** (Kodi + Discord on the same PC) and **remotely** (e.g. LibreELEC → a PC running Discord).

---

## ✨ Features

- 🎥 **Video presence** — movies, TV shows, YouTube and general streams (with thumbnails)
- 🎵 **Music presence** — track, artist and album, with album art (iTunes artwork lookup)
- ⏸️ **Pause / resume / stop** handling — timestamps freeze on pause, presence clears on stop
- 🖼️ **Thumbnails** — resolves Kodi `image://` URLs, YouTube video IDs, and remote artwork
- 🌐 **Remote bridge mode** — run Discord on a PC, let a LibreELEC/Kodi device publish to it
- 🔒 **Privacy modes** — full details, title only, or fully generic
- 🚫 **Blacklist** — skip sharing info for selected source addons (e.g. YouTube). Run the addon (Enter on it in *My add-ons*) → *Manage addon blacklist*.
- ⚙️ **Configurable** — client ID, update interval, timestamps, connection mode, presence title

## 📦 Installation

### 1. Create a Discord application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) → **New Application**.
2. Give it a name (e.g. `KodiCord`).
3. Copy the **Application ID** (Client ID).

### 2. Install the Kodi addon

**From a zip (recommended):**

1. Download the latest `service.kodicord-*.zip` from [Releases](../../releases).
2. In Kodi: **Add-ons → Install from zip file** → select the zip.
3. The service starts automatically.

**Manually:**

1. Copy the `service.kodicord` folder to your Kodi addons directory:
   - Linux/macOS: `~/.kodi/addons/`
   - LibreELEC: `/storage/.kodi/addons/`
2. Restart Kodi.

### 3. Configure

In Kodi: **Add-ons → My add-ons → Services → KodiCord → Configure**

- **Enable** — turn on Rich Presence
- **Connection mode** — *Local Discord client* or *Remote bridge (PC)*
- **Discord Application (Client) ID** — paste the ID from step 1
- **What to share** — full details / title only / generic
- **Show timestamps** — show elapsed/remaining time
- **Presence title** — application name / media type on Kodi / custom text

## 🌐 Remote mode (LibreELEC → PC)

Run the companion bridge on the PC that hosts your Discord client:

```bash
cd companion
python3 discord_bridge.py --client-id YOUR_CLIENT_ID --port 8765
```

Then in the Kodi addon settings:

- **Connection mode** → *Remote bridge (PC)*
- **Bridge host** → your PC's IP (e.g. `192.168.1.10`)
- **Bridge port** → `8765`
- **Bridge auth token** → optional shared secret

Make sure your firewall allows the chosen port.

> 💡 Tip: keep the bridge running with `systemd`, `tmux`, or a scheduled task.

## 🎛️ Presence title

Discord always prefixes the top line with *Playing / Listening to / Watching*.
By default KodiCord uses your Discord application's name. You can override it:

- **Application name** (default) — uses the name from the Developer Portal
- **Media title** — the video title, or `Artist - Title` for music (default)
- **Media type on Kodi** — e.g. *Listening to music on Kodi*
- **Custom** — any text you like

Change it in **Settings → Presence → Presence title**.

## 🛠️ Development

```bash
# Syntax check
python3 -m compileall -q .

# Run the bridge locally
cd companion && python3 discord_bridge.py --client-id YOUR_CLIENT_ID --port 8765
```

### Project layout

```
.
├── addon.xml              # Kodi addon manifest (service entry point)
├── service.py             # Kodi monitor: metadata, pause/stop, calls IPC
├── addon.py               # Settings dialog + connection test helpers
├── resources/
│   ├── settings.xml       # Kodi settings schema
│   ├── icon.png
│   └── lib/
│       ├── discord_ipc.py # Pure-Python Discord IPC client + activity helpers
│       └── remote_client.py
├── companion/
│   ├── discord_bridge.py  # PC-side HTTP bridge → Discord IPC
│   └── discord_ipc.py     # Copy used by the bridge
└── docs/
```

## 🐛 Troubleshooting

- **Nothing shows up in Discord** — make sure Discord is running and that *Activity Status* is enabled (Settings → Activity Privacy → "Display current activity as a status message").
- **Thumbnails missing** — Discord only accepts `https://` image URLs. Local `image://` URLs are decoded; YouTube IDs are resolved to `i.ytimg.com`.
- **Remote mode fails** — verify the bridge is running (`curl http://PC_IP:8765/ping`) and the firewall allows the port.
- **Old application name still shown** — Discord caches the app name; fully quit and reopen Discord, or wait ~1 hour for the cache to expire. KodiCord also sends the current name in the payload to bypass the stale cache.
- **Album art wrong** — KodiCord queries the iTunes Search API by `artist + title` and caches by `artist-title`.

## 🤝 Contributing

Issues and pull requests are welcome. Please:

1. Fork the repo and create a feature branch.
2. Keep changes consistent with the existing style.
3. Run `python3 -m compileall -q .` before submitting.

## 📄 License

Released under the [MIT License](LICENSE).

---

Made with ❤️ for the Kodi & Discord communities.
