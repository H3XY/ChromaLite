# ChromaLite

A lightweight lighting app for gaming keyboards, mice and mousepads on
Windows. Control Razer devices without the Synapse interface, light up devices
from other brands through Windows Dynamic Lighting, and play your old
**Synapse 3 Chroma Studio effects** on any of them.

> ChromaLite is an independent project. It is not affiliated with, endorsed by,
> or supported by Razer Inc. or any other device maker. "Razer", "Chroma" and
> "Synapse" are trademarks of Razer Inc.; other names are trademarks of their
> owners.

## Features

- **Works across brands**
  - **Razer** devices through the Razer Chroma SDK that comes with Synapse —
    including while ChromaLite runs in the background.
  - **Logitech, Corsair, SteelSeries, HyperX, ASUS and more** through Windows 11
    **Dynamic Lighting**, for any device that supports it.
  - A device is only ever controlled one way: Razer devices use Synapse when
    it's installed, and fall back to Dynamic Lighting when it isn't.
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
- **Runs in the system tray** like Synapse: closing the window keeps your
  lighting on. Optional start with Windows. One instance at a time.

## Requirements

- Windows 10 or 11 (Dynamic Lighting devices need Windows 11).
- For Razer devices: Razer Synapse installed, with its **Razer Chroma SDK**
  services running. The Synapse window itself doesn't need to work or be open.
- Microsoft Edge WebView2 Runtime (built into Windows 11; most Windows 10 PCs
  already have it).

## Install

Download `ChromaLite.exe` from the [Releases](../../releases) page and run it.
No installer, no Python needed.

Windows SmartScreen may warn about an unsigned app the first time; choose
**More info → Run anyway**.

## Using it

- **Devices** shows everything ChromaLite is lighting, with live previews.
  Each device has an on/off switch; click a device to customize it.
- **Lighting** sets the effect for **All devices**. On a device's own page,
  turn off **Sync with All devices** to give it a different effect.
- **Effect Library** holds your Chroma Studio effects: **Import effects** adds
  `.ChromaEffects` files, and each can be applied to all devices or picked per
  device under *Chroma Studio effects*.
- **Settings**: start with Windows, keep running in the tray, key-press
  lighting, and the status of each device source.

Closing the window keeps ChromaLite in the system tray. Click the tray icon to
reopen it, or right-click → **Exit** to quit (lighting then goes back to
Synapse / Windows).

Settings and imported effects live in `%APPDATA%\ChromaLite`.

## About Dynamic Lighting devices

Windows only lets the app **in the foreground** control Dynamic Lighting
devices (background control is reserved for apps installed from a package
with special permission). So non-Razer devices follow ChromaLite while its
window is active, and Windows takes them back otherwise; the app shows these
devices as *Paused* meanwhile. Razer devices aren't affected — they're
controlled through Synapse in the background.

## Troubleshooting

**Lights hyper-flash, even on a solid color.** Another program is fighting over
your devices. The usual culprits are ASUS Armoury Crate / Aura Sync, other RGB
suites (SignalRGB, OpenRGB, iCUE, G HUB, …) and Windows Dynamic Lighting's own
effects. Exit the other program or stop it controlling those devices; in
Windows, check *Settings → Personalization → Dynamic Lighting*.

**Razer Chroma shows "Razer Synapse not found".** The Razer Chroma SDK services
aren't running. Reinstall or repair Synapse, or start the *Razer Chroma SDK
Server* service.

**A device isn't listed.** Razer devices need Synapse; other brands need
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
pyw chromalite.pyw
```

Build the single-file `.exe` into `dist\` (creates a local build environment
with PyInstaller):

```
powershell -ExecutionPolicy Bypass -File build.ps1
```

If pip fails with a long-path error, point the build environment at a shorter
folder first: `$env:CHROMALITE_VENV = "C:\clb"`.

## How it works

- `chromalite.pyw` — app entry: the window (an HTML interface shown with
  pywebview / WebView2), the bridge the interface calls, the tray and startup.
- `ui/` — the interface (HTML, CSS, JavaScript; no frameworks).
- `engine.py` — settings, built-in effects and the render loop: collects
  devices from every backend, works out each one's effect and streams frames
  at 30 fps.
- `devices.py` — the device model every backend produces: LEDs with positions
  on a shared desk layout, so effects flow across devices.
- `backend_razer.py` — Razer devices via the Chroma SDK REST API
  (`CHROMA_CUSTOM2` frames, heartbeat), with device names from Windows.
- `backend_dynlight.py` — any brand via Windows Dynamic Lighting (LampArray),
  using each lamp's real position and key mapping.
- `chroma_effects.py` — the `.ChromaEffects` reader (a zip holding one XML
  document of layers → regions → device cells), the retargeting onto your
  devices, the layer renderers, plus key-press polling and the audio meter.
- `tray.py` — the tray icon (Win32 API via ctypes).
- `tools/make_icon.py` — generates the app icon.

## License

[MIT](LICENSE)
