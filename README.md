# ChromaLite

A lightweight lighting controller for Razer Chroma devices on Windows — a small
alternative to the Synapse lighting UI that can also play your old **Synapse 3
Chroma Studio effect files** on whatever Razer devices you own today.

> ChromaLite is an independent project. It is not affiliated with, endorsed by,
> or supported by Razer Inc. "Razer", "Chroma" and "Synapse" are trademarks of
> Razer Inc.

## Features

- **Built-in effects:** Static, Breathing, Duo Pulse, Spectrum Cycle, Rainbow
  Wave, Gradient Wave, Starlight, Off — with two colors, quick presets,
  brightness and speed.
- **Plays Chroma Studio exports (`.ChromaEffects`)**, including layered effects
  with transparency: static, wave, spectrum, starlight, fire, color wheel,
  reactive (keys light when pressed), ripple, and audio meter (follows what
  your PC is playing).
- **Retargets effects to your hardware.** Effects made for other devices still
  work:
  - keyboard keys are matched by identity, so a WASD highlight made on a
    Huntsman lands on WASD on a BlackWidow;
  - other LEDs are matched by relative position (mouse to mouse, mousepad to
    mousepad);
  - device types the effect never targeted borrow its keyboard layout, so your
    whole setup lights up;
  - animations flow across a shared desk layout (keyboard → mouse → mousepad).
- **Keyboard underglow / side lighting** via the SDK's extended keyboard grid.
- **Smooth output:** soft gradient edges and per-LED easing between frames.
- Per-device on/off, optional start with Windows (minimized), settings saved
  between runs, single instance.
- Small: one `.exe`, or two Python files using only the standard library.

## Requirements

- Windows 10 or 11.
- Razer Synapse installed, with the **Razer Chroma SDK** services running.
  ChromaLite talks to the Chroma SDK's local REST server
  (`http://localhost:54235`), not to the hardware directly. The Synapse
  *window* itself doesn't need to work or be open.

## Install

Download `ChromaLite.exe` from the
[Releases](../../releases) page and run it. No installer, no Python needed.

Windows SmartScreen may warn about an unsigned app the first time; choose
**More info → Run anyway**.

## Usage

- Pick an effect from the **Effect** list. Brightness and speed apply to every
  effect; the two colors apply to the built-in effects.
- **Import…** adds `.ChromaEffects` files (Chroma Studio's export format). They
  appear in the list as `File: <name>`. **Folder** opens where they're stored.
- **Minimize** ChromaLite to keep your lighting. **Closing** it hands lighting
  back to Synapse.
- Tick **Start with Windows (minimized)** to launch it at sign-in.

Settings and imported effects live in `%APPDATA%\ChromaLite`.

## Troubleshooting

**Lights hyper-flash, even on a solid color.** Another program is fighting over
your Razer devices. The usual culprits are ASUS Armoury Crate / Aura Sync, other
RGB suites (SignalRGB, OpenRGB, iCUE, …) and Windows Dynamic Lighting. Exit the
other program and/or stop it controlling your Razer devices: in Windows, check
*Settings → Personalization → Dynamic Lighting* (background light control and
each Razer device's "Use Dynamic Lighting on my devices" toggle).

**Status says "Chroma SDK not reachable".** The Razer Chroma SDK services aren't
running. Reinstall or repair Synapse, or start the *Razer Chroma SDK Server*
service.

**A Chroma Studio effect looks different from how it did in Synapse.** The
`.ChromaEffects` format is undocumented, so some timings (wave speed and width,
starlight density) are best-effort approximations. Issues with the file
attached are welcome.

## Run or build from source

Run directly (Python 3.10+, no packages needed):

```
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

- `chromalite.pyw` — the window, settings, built-in effects and the render
  loop. It registers with the Chroma SDK, then streams per-LED frames
  (`CHROMA_CUSTOM2`) at 30 fps with a heartbeat to keep the session alive.
- `chroma_effects.py` — the `.ChromaEffects` reader (a zip holding one XML
  document of layers → regions → device cells), the retargeting onto your
  devices, the layer renderers, plus key-press polling and the Windows audio
  peak meter used by the reactive, ripple and audio-meter layers.
- `tools/make_icon.py` — generates the app icon.

## License

[MIT](LICENSE)
