[![Vibe Coded](https://img.shields.io/badge/Vibe_Coded-✨-8A2BE2?style=for-the-badge)](https://github.com)

# 🎬 KodiCord — Discord Rich Presence for Kodi

![KodiCord icon](icon.png)

[![Discord](https://img.shields.io/discord/1468295714961494029?color=7289da&label=Join%20Our%20Discord&logo=discord&logoColor=white&style=for-the-badge)](https://discord.gg/UbPRh74PzV)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Kodi](https://img.shields.io/badge/Kodi-19%2B-blue?logo=kodi)](https://kodi.tv)
[![Python](https://img.shields.io/badge/Python-3.x-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Discord](https://img.shields.io/badge/Discord-Rich%20Presence-5865F2?logo=discord&logoColor=white)](https://discord.com/developers/applications)

> Show what you're watching or listening to on Kodi — live, in your Discord status.
> Works **locally** (Kodi + Discord on the same PC) and **remotely** (e.g. LibreELEC → a PC running Discord).

---

## ✨ Features

- 🎥 **Video presence** — movies, TV shows, YouTube and general streams, with thumbnails
- 🎵 **Music presence** — track, artist and album, with album art
- ⏸️ **Pause / resume / stop** handling — timestamps freeze on pause, presence clears on stop
- 🖼️ **Thumbnails** — resolves Kodi `image://` URLs, YouTube video IDs, and remote artwork
- 🔗 **Clickable links** — click the thumbnail or title in Discord to open the video (YouTube) or song (any platform)
- 🌐 **Remote bridge mode** — run Discord on a PC, let a LibreELEC/Kodi device publish to it
- 🔒 **Privacy modes** — full details, title only, or fully generic
- 🚫 **Per-addon blacklist** — skip presence for chosen source addons
- 🎵 **Song links (optional)** — universal links for songs across platforms

---

<details>
<summary><b>📸 Examples</b></summary>

### Listening to music

![Listening to music example](docs/music-example.png)

### Watching a video (YouTube)

![Watching a video example](docs/video-example.png)

> **Tip:** Click the thumbnail or title in Discord to open the video (YouTube) or song (any platform).

</details>

<details>
<summary><b>📦 Installation</b></summary>

1. Download the latest release zip from the [Releases page](https://github.com/Nigel1992/KodiCord/releases).
2. In Kodi: **Add-ons → Install from zip file** → select the downloaded zip.
3. Enable the addon if prompted.

</details>

<details>
<summary><b>⚙️ Configuration</b></summary>

Open **Add-ons → My add-ons → Services → KodiCord → Configure**.

| Setting | Description |
|---|---|
| **Enable Discord Rich Presence** | Turn presence on/off |
| **Connection mode** | Local Discord client or Remote bridge (PC) |
| **Client ID** | Discord application (client) ID |
| **Update interval** | How often presence is refreshed (seconds) |
| **Clear on stop** | Clear presence when nothing is playing |
| **Show timestamps** | Show elapsed/remaining time |
| **Bridge host / port / token / timeout** | Remote bridge connection settings |
| **Privacy mode** | Full details, title only, or generic |
| **Use filename if no metadata** | Fall back to filename |
| **Blacklisted addons** | Comma-separated addon IDs to skip |
| **Manage addon blacklist** | Open a picker to choose blacklisted addons |
| **Presence title** | Discord application name, media title, media type, or custom text |
| **Custom presence title** | Custom text for presence title |

</details>

<details>
<summary><b>🌐 Remote Bridge Mode</b></summary>

Run the companion bridge on a PC that has Discord installed, then point Kodi to it:

1. Start `companion/discord_bridge.py` on the PC.
2. In KodiCord settings, set **Connection mode** to **Remote bridge (PC)**.
3. Enter the PC's IP/hostname, port, and optional token.

> On Windows and Linux the bridge shows a **KodiCord icon in the system tray (notification area)** while it runs, so you can confirm it is active. Right-click the icon for options: toggle **Monochrome/Color** icon, **Restart Discord connection**, **Show status**, and **Exit KodiCord bridge**. Run it with `pythonw` instead of `python` on Windows if you do not want a console window.

> On Linux, the bridge also detects Discord installations packaged as a Snap or Flatpak.

</details>

<details>
<summary><b>🚫 Blacklist</b></summary>

Skip sharing presence for selected source addons:

- Use **Manage addon blacklist** in settings to pick addons from a list, or
- Manually enter comma-separated addon IDs in **Blacklisted addons**.

</details>

<details>
<summary><b>🔒 Privacy</b></summary>

Choose how much detail is shared:

- **Full title and details**
- **Title only**
- **Generic ('Watching a movie')**

</details>

<details>
<summary><b>🔑 Song Links (optional)</b></summary>

A default MusicLink API key is included so the feature works out of the box for everyone.
It is **free to use**, but limited to ~300 lookups/month. For heavier use, create your own key:

1. Sign up at [song.link (Odesli)](https://song.link) and obtain an API key.
2. Edit `MUSICLINK_API_KEY` in both:
   - `resources/lib/discord_ipc.py`
   - `companion/discord_ipc.py`
3. Rebuild/reinstall the addon.

This feature is **optional** — presence still works without it. A settings option to enter your own key without editing files is coming soon.

</details>

<details>
<summary><b>🙏 Credits & Sources</b></summary>

- **Kodi** — JSON-RPC / player & addon APIs (https://kodi.tv)
- **Discord** — Rich Presence IPC (https://discord.com/developers)
- **iTunes Search API** — album artwork lookup for music (https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/)
- **YouTube** — video thumbnails via `img.youtube.com`
- **Songlink / Odesli API** — universal links for songs across platforms (https://song.link)
- **LibreELEC** — remote bridge hosting (https://libreelec.tv)

Special thanks to the Kodi and LibreELEC communities.

Tray icon: [Revive icons created by meaicon - Flaticon](https://www.flaticon.com/free-icons/revive)

</details>