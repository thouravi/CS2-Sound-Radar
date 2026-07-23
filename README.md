# CS2 Sound Radar

Always-on-top desktop overlay that visualizes **stereo direction** from your system audio (WASAPI loopback). Built for Counter-Strike 2 practice and awareness — you still hear the game normally while a floating radar shows left/right balance and intensity in real time.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6)
![License](https://img.shields.io/badge/License-MIT-green)

## Features

- **WASAPI loopback capture** — listens to what your speakers/headphones are playing; no mic required and game audio is uninterrupted
- **Always-on-top overlay** — stays visible over CS2 (use **Fullscreen Windowed** in-game)
- **Live stereo radar** — angle, intensity trail, and L/R meters
- **Device picker** — choose which output’s loopback to capture (handy with headsets or multiple devices)
- **System tray** — show window, restart capture, or quit
- **Drag to move** — grab the header to reposition the window

## Requirements

- **Windows** (WASAPI loopback)
- **Python 3.10+** on `PATH`
- Packages listed in `requirements.txt`:
  - `numpy`
  - `PySide6`
  - `SoundCard`

## Quick start

### Option A — double-click launcher

1. Double-click **`START_RADAR.bat`** or **`run.bat`**
2. The script installs missing packages if needed, then opens the overlay

### Option B — terminal

```bat
cd path\to\CS2 Sound Radar
python -m pip install -r requirements.txt
python radar_overlay.py
```

## Usage

1. Start the overlay **before or while** CS2 is running.
2. In CS2, prefer **Fullscreen Windowed** so the radar stays on top.
3. In the overlay, pick the **Audio** device that CS2 actually plays on (often your headset or default speakers).
4. Play or listen in-game — footsteps and gunfire with stereo panning should move the radar blob left/right.
5. **Restart** after switching audio devices; **Refresh** reloads the loopback list.

### Shortcuts

| Key / action | Effect |
|--------------|--------|
| Drag header | Move window |
| `Esc` | Close overlay |
| `R` | Restart capture |
| Tray menu | Show / restart / quit |

## Project layout

```
audio/
├── radar_overlay.py   # Main application
├── requirements.txt   # Python dependencies
├── run.bat            # Launcher (checks Python, installs deps, runs app)
├── START_RADAR.bat    # Shortcut that calls run.bat
├── README.md
└── .gitignore
```

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| No window / instant exit | Open `radar_log.txt` in this folder (created on each run). |
| `Python not found` | Install Python from [python.org](https://www.python.org/downloads/) and enable **Add python.exe to PATH**. |
| Import / missing package errors | `python -m pip install -r requirements.txt` |
| No loopback devices | Confirm Windows desktop audio works; try another output in the combo box. |
| Radar flat / no movement | Select the same device CS2 uses; ensure game audio is stereo (not mono). |
| Overlay hidden under game | Set CS2 to **Fullscreen Windowed** (not exclusive fullscreen). |

Logs are written to `radar_log.txt` each launch (gitignored).

## How it works

1. **SoundCard** opens a stereo WASAPI loopback on the selected output.
2. Each block computes L/R RMS → balance and intensity.
3. **PySide6** draws a circular radar with a smoothed angle, trail, and meters on an always-on-top window.

This is **direction-of-arrival from stereo balance**, not full 360° spatial audio analysis. It helps visualize panning (left vs right) from normal game output.

## Is this VAC-safe?

**Short answer:** From how this app works, it is **very unlikely** to trigger **VAC**. It is **not** a game cheat in the VAC sense — but **nobody can promise “VAC-safe forever.”**

### Why it shouldn’t trip VAC

VAC mainly looks for things that **touch the game process or game files**, such as:

- DLL / code injection into CS2  
- Reading or writing game memory  
- Modified game binaries  
- Known cheat drivers / signatures  

This tool does **none** of that. It:

1. Runs as a **separate** Python/Qt process  
2. Captures **Windows system audio** via WASAPI loopback (what you already hear)  
3. Draws an **always-on-top overlay** with PySide6  
4. Never attaches to, injects into, or scrapes CS2  

Technically it’s closer to a visualizer of your headphones than to a wallhack or aimbot.

### What “VAC-safe” does *not* mean

| Concern | Reality |
|--------|---------|
| **VAC ban** | Unlikely for external audio-only tools that don’t touch CS2 |
| **Valve ToS / “assists”** | Valve can still care about tools that give a competitive edge; enforcement is usually aimed at real cheats, not separate audio meters |
| **Guarantees** | No third-party app can honestly say “100% VAC-safe forever” — rules and detection change |

### Practical takeaway

- **Architecture-wise:** external, read-only loopback audio → **not** classic VAC territory.  
- **Risk level:** low for a **VAC ban** specifically.  
- **Still:** use at your own risk; treat it as a training/awareness helper, not something Valve has “approved.”

## Disclaimer

For personal use and training. Respect Valve’s ToS and local laws. This tool only analyzes audio you already hear; it does not inject into CS2, read game memory, or modify game files. Use at your own risk.

## License

MIT — free to use, modify, and share.
```
