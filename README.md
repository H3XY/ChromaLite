# Prismatic

*Formerly ChromaLite.*

A lightweight lighting app for gaming keyboards, mice and mousepads on
Windows. Control Razer devices without the Synapse interface, light up devices
from other brands through Windows Dynamic Lighting, and play your old
**Synapse 3 Chroma Studio effects** on any of them.

> Prismatic is an independent project. It is not affiliated with, endorsed by,
> or supported by Razer Inc. or any other device maker. "Razer", "Chroma" and
> "Synapse" are trademarks of Razer Inc.; other names are trademarks of their
> owners.

## Features

- **Works across brands**
  - **Razer** devices through the Razer Chroma SDK that comes with Synapse —
    including while Prismatic runs in the background.
  - **Razer without Synapse:** supported models (BlackWidow V4 Pro,
    DeathAdder V2, Firefly V2) are controlled **directly over USB** when
    Synapse isn't installed or running — in the background too.
  - **Logitech, Corsair, SteelSeries, HyperX, ASUS and more** through Windows 11
    **Dynamic Lighting**, for any device that supports it.
  - A device is only ever controlled one way: Razer devices use Synapse when
    it's available, then direct USB, then Dynamic Lighting.
- **Built-in effects:** Static, Breathing, Duo Pulse, Spectrum Cycle, Rainbow
  Wave, Gradient Wave, Starlight, Off — with colors, brightness and speed.
- **Plays Chroma Studio exports (`.ChromaEffects`)**, including layered effects
  with transparency: static, wave, spectrum, starlight, fire, color wheel, key
  press, ripple and audio meter. Effects are remapped onto whatever devices you
  have: keys by identity (so a WASD highlight lands on WASD on any keyboard),
  everything else by position.
- **Per-device effects:** give each device its own effect, colors, brightness
  and speed, or let them all sync to one.
- **Live previews** of every device in the app, an **effect library** with
  color thumbnails, and smooth, flicker-free output.
- **Button customization:** give your mouse's side buttons and keyboard macro
  keys new jobs — a key or shortcut, media controls, opening an app or
  website, typing text, or a sequence of steps.
- **Runs in the system tray** like Synapse: closing the window keeps your
  lighting on. Optional start with Windows. One instance at a time.

## Requirements

- Windows 10 or 11 (Dynamic Lighting devices need Windows 11).
- For Razer devices: either Razer Synapse installed (its **Razer Chroma SDK**
  services must be running; the Synapse window itself doesn't need to work or
  be open), or — for the models listed above — nothing at all.
- Microsoft Edge WebView2 Runtime (built into Windows 11; most Windows 10 PCs
  already have it).

## Install

1. Download `Prismatic-<version>-windows.zip` from the [Releases](../../releases)
   page.
2. Extract it anywhere (for example `Documents\Prismatic`) and run
   `Prismatic.exe` inside the extracted folder. Keep the folder together — the
   `.exe` needs the files next to it.

No installer, no Python needed. To update, replace the folder with the new one;
your settings live elsewhere and carry over.

Windows SmartScreen may warn about an unsigned app the first time; choose
**More info → Run anyway**. See *Antivirus warnings* below if your antivirus
flags the app.

## Using it

- **Devices** shows everything Prismatic is lighting, with live previews.
  Each device has an on/off switch; click a device to customize it.
- **Lighting** sets the effect for **All devices**. On a device's own page,
  turn off **Sync with All devices** to give it a different effect.
- **Effect Library** holds your Chroma Studio effects: **Import effects** adds
  `.ChromaEffects` files, and each can be applied to all devices or picked per
  device under *Chroma Studio effects*.
- **Buttons** customizes your mouse's Back/Forward side buttons and keyboard
  macro keys. Click **Edit** on a row to choose what it does, and **Test** to
  try it. Macro keys work through **F13–F24**, keys no keyboard actually has:
  in Razer Synapse, set each macro key to a different one (for example
  M1 → F13), then press it on the Buttons page to see which row lights up.
  Customized buttons work while Prismatic is running, including from the tray.
- **Settings**: start with Windows, keep running in the tray, key-press
  lighting, and the status of each device source.

Closing the window keeps Prismatic in the system tray. Click the tray icon to
reopen it, or right-click → **Exit** to quit (lighting then goes back to
Synapse / Windows).

Settings and imported effects live in `%APPDATA%\Prismatic` (carried over automatically from ChromaLite).

## About Dynamic Lighting devices

Windows only lets the app **in the foreground** control Dynamic Lighting
devices (background control is reserved for apps installed from a package
with special permission). So non-Razer devices follow Prismatic while its
window is active, and Windows takes them back otherwise; the app shows these
devices as *Paused* meanwhile. Razer devices aren't affected — they're
controlled through Synapse in the background.

## Troubleshooting

**Antivirus warnings.** Prismatic isn't code-signed yet, and apps packaged with
PyInstaller that run in the tray and watch key presses can trip antivirus
*heuristics* (detections ending in `!ml` or labeled "dropper" are guesses, not
known malware). Version 2.0.0–2.1.0 shipped as a single self-extracting `.exe`,
which Microsoft Defender flagged as `Trojan:Win32/Bearfoos.A!ml`; from 2.2.0 the
app ships as a folder, which avoids the main trigger. You can check any release
yourself: each release lists its files' SHA-256 hashes, and you can look a hash
up on [VirusTotal](https://www.virustotal.com) or build the app from this
source. False positives can be reported to Microsoft at
[microsoft.com/wdsi/filesubmission](https://www.microsoft.com/en-us/wdsi/filesubmission).

**Lights hyper-flash, even on a solid color.** Another program is fighting over
your devices. The usual culprits are ASUS Armoury Crate / Aura Sync, other RGB
suites (SignalRGB, OpenRGB, iCUE, G HUB, …) and Windows Dynamic Lighting's own
effects. Exit the other program or stop it controlling those devices; in
Windows, check *Settings → Personalization → Dynamic Lighting*.

**Razer Chroma shows "Razer Synapse not found".** The Razer Chroma SDK services
aren't running. Reinstall or repair Synapse, or start the *Razer Chroma SDK
Server* service.

**Razer direct USB says "Razer Synapse is running".** Direct USB control
steps aside while Synapse's app is open, because two programs writing to the
same device makes it flicker. Close Synapse fully (tray icon → Exit), or let
Prismatic use Synapse's Chroma SDK instead.

**A device isn't listed.** Razer devices need Synapse unless they're one of the
directly supported models; other brands need
Windows 11 Dynamic Lighting support (check *Settings → Personalization →
Dynamic Lighting* — if the device isn't listed there, Windows can't control
it).

**A Chroma Studio effect looks different from how it did in Synapse.** The
`.ChromaEffects` format is undocumented, so some timings (wave speed and width,
starlight density) are best-effort approximations. Issues with the file
attached are welcome.

## Run or build from source

Requires Python 3.10+.

```
pip install -r requirements.txt
pyw prismatic.pyw
```

Build the app into `dist\Prismatic\` and the release zip
`dist\Prismatic-<version>-windows.zip` (creates a local build environment with
PyInstaller):

```
powershell -ExecutionPolicy Bypass -File build.ps1
```

If pip fails with a long-path error, point the build environment at a shorter
folder first: `$env:PRISMATIC_VENV = "C:\clb"`.

## How releases are built

Release zips are built by GitHub Actions on GitHub's own Windows machines
(`.github/workflows/build.yml`), not on anyone's PC: pushing a version tag builds
the app from that exact commit and attaches the zip and its SHA-256 to a draft
release, with a link to the build log. Every push and pull request is built the
same way, so you can download a test build from the run's artifacts.

## How it works

- `prismatic.pyw` — app entry: the window (an HTML interface shown with
  pywebview / WebView2), the bridge the interface calls, the tray and startup.
- `ui/` — the interface (HTML, CSS, JavaScript; no frameworks).
- `engine.py` — settings, built-in effects and the render loop: collects
  devices from every backend, works out each one's effect and streams frames
  at 30 fps.
- `devices.py` — the device model every backend produces: LEDs with positions
  on a shared desk layout, so effects flow across devices.
- `backend_razer.py` — Razer devices via the Chroma SDK REST API
  (`CHROMA_CUSTOM2` frames, heartbeat), with device names from Windows.
- `backend_razer_usb.py` — supported Razer devices directly over USB (HID
  feature reports, per-model LED layouts), used when Synapse isn't available.
- `backend_dynlight.py` — any brand via Windows Dynamic Lighting (LampArray),
  using each lamp's real position and key mapping.
- `chroma_effects.py` — the `.ChromaEffects` reader (a zip holding one XML
  document of layers → regions → device cells), the retargeting onto your
  devices, the layer renderers, plus key-press polling and the audio meter.
- `buttons.py` — button customization: F13–F24 through Windows' standard
  hotkey API (no keyboard hook), mouse side buttons through a low-level mouse
  hook that's only installed while one is customized, and the actions
  (simulated keys, media keys, typing, opening apps/links, sequences).
- `tray.py` — the tray icon (Win32 API via ctypes).
- `tools/make_icon.py` — generates the app icon; `tools/make_version_info.py`
  — the version details shown in the `.exe`'s Properties.

## License

[MIT](LICENSE)
