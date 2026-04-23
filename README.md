# 🧇 WaffleEncoder

> *Crispy HAP & ProRes transcoding · demoscene-grade UI · single 47 MB .exe*

A tiny Python / Tkinter GUI that wraps **ffmpeg** to batch-transcode video clips to **HAP / HAP Alpha / HAP Q** or **Apple ProRes** (Proxy / LT / Standard / HQ / 4444 / 4444 XQ). Born out of the need to feed Resolume / Notch / TouchDesigner / Nuke pipelines without typing the same `ffmpeg -c:v hap -format hap_alpha -vf 'scale=...'` incantation for the hundredth time.

```
██╗    ██╗ █████╗ ███████╗███████╗██╗     ███████╗
██║    ██║██╔══██╗██╔════╝██╔════╝██║     ██╔════╝
██║ █╗ ██║███████║█████╗  █████╗  ██║     █████╗
██║███╗██║██╔══██║██╔══╝  ██╔══╝  ██║     ██╔══╝
╚███╔███╔╝██║  ██║██║     ██║     ███████╗███████╗
 ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝     ╚═╝     ╚══════╝╚══════╝
        · E · N · C · O · D · E · R ·
```

---

## ✨ Features

- **Batch queue** — drop files, whole folders, or both; shows name / size / source path.
- **Codecs** — HAP · HAP Alpha · HAP Q · ProRes (Proxy / LT / Standard / HQ / 4444 / 4444 XQ), each with the right pixel format auto-picked (alpha preserved on the 4444 variants).
- **HAP "divisible by 4"** auto-scaler with three rounding modes (nearest / round up / round down) — HAP's hard constraint, handled so you never get `Dimensions must be a multiple of 4` errors.
- **Frame-rate reinterpretation** — same frames, re-stamped at a new rate, so a 120 fps clip at 60 fps becomes twice as long. True reinterpret, not drop/duplicate.
- **Audio** — keep / strip / swap codec (`pcm_s16le`, `pcm_s24le`, `aac`, `copy`).
- **Live log** with the actual ffmpeg command and running progress bar.
- **Single-file exe** — PyInstaller build bundles Python, Tkinter and ffmpeg into one 47 MB `.exe`. No install, no PATH drama.
- **Terminal / demoscene UI** — phosphor green, magenta, cyan, ASCII block header, scrolling credits ticker. Because why not.

---

## 🚀 Quick start

### Grab the prebuilt exe

`dist/WaffleEncoder.exe` is fully self-contained — double-click and go. ffmpeg is inside the exe.

### Run from source (no venv needed)

```bat
python main.py
```

or the provided launcher:

```bat
run.bat
```

Requirements: **Python 3.10+** (uses Tkinter which ships with Python on Windows). No pip packages at runtime.

### Build your own exe

```bat
build.bat
```

`build.bat` invokes PyInstaller with `--onefile --windowed`. If a file named `ffmpeg.exe` is sitting next to `build.bat`, it gets baked into the exe via `--add-binary`; otherwise the exe falls back to `FFMPEG_BIN` / `PATH` / sibling file at runtime.

---

## 🎞️ ffmpeg resolution order

The app finds an ffmpeg binary in this order (first hit wins):

1. **Embedded in the exe** (PyInstaller's `_MEIPASS` unpack dir)
2. `FFMPEG_BIN` environment variable
3. `ffmpeg.exe` sitting next to `main.py` / the exe
4. `ffmpeg` on `PATH`

The header of the app shows which one it picked, e.g. `// ffmpeg: [EMBEDDED] C:\...\Temp\_MEIxxx\ffmpeg.exe`.

---

## 📐 HAP and the divisible-by-4 rule

HAP encoders refuse to process frames whose width or height isn't a multiple of 4 (a GPU-block alignment constraint, not an ffmpeg quirk). WaffleEncoder's **Force resolution divisible by 4** option adds a `scale` filter that rounds each dimension to the nearest / next / previous multiple of 4:

| Mode                     | Behaviour                                       | Resulting size vs source |
|--------------------------|-------------------------------------------------|--------------------------|
| Nearest *(stretch)*      | `round(iw/4)*4 : round(ih/4)*4`                 | ±2 px per axis           |
| Round up *(stretch)*     | `ceil(iw/4)*4 : ceil(ih/4)*4`                   | 0–3 px bigger            |
| Round down *(crop-like)* | `floor(iw/4)*4 : floor(ih/4)*4`                 | 0–3 px smaller           |

All three use the `scale` filter (not crop), so content is stretched — you never lose pixels, at worst a handful of rows/columns are interpolated.

---

## ⏱️ Reinterpret frame rate

When *Reinterpret fps* is ticked, the target fps is applied as an **input-side** option (`ffmpeg -r N -i input.mov …`). Every source frame is kept and re-stamped at the new rate, so **the clip's duration changes** — a 120 fps / 10 s source re-interpreted to 60 fps becomes 60 fps / 20 s, in half-speed playback.

> ⚠️ Audio is **not** time-stretched. If you keep audio on a reinterpreted clip it'll end earlier or later than the video. For HAP / ProRes motion-graphics sources this is usually fine; otherwise uncheck *Keep audio*.

---

## 🎨 ProRes profiles

Uses ffmpeg's `prores_ks` encoder (more accurate than the default `prores`).

| UI label        | `-profile:v` | Pixel format    | Alpha |
|-----------------|--------------|------------------|-------|
| Proxy           | 0            | `yuv422p10le`    | no    |
| LT              | 1            | `yuv422p10le`    | no    |
| Standard (422)  | 2            | `yuv422p10le`    | no    |
| HQ (422 HQ)     | 3            | `yuv422p10le`    | no    |
| 4444            | 4            | `yuva444p10le`   | **yes** |
| 4444 XQ         | 5            | `yuva444p10le`   | **yes** |

Vendor tag is set to `apl0` so NLEs recognise the files as Apple ProRes.

---

## 📂 Project layout

```
WaffleEncoder/
├── main.py              # Tkinter UI (demoscene edition)
├── transcoder.py        # ffmpeg command builder + runner + progress parser
├── install.bat          # no-op informational script (no deps to install)
├── run.bat              # python main.py
├── build.bat            # PyInstaller → dist/WaffleEncoder.exe
├── requirements.txt     # empty — stdlib only at runtime
├── .gitignore
├── README.md
├── ffmpeg.exe           # optional, git-ignored; drop here before build.bat to embed
└── dist/
    └── WaffleEncoder.exe
```

`main.py` is ≈550 lines of Tkinter + a single `Panel`/`TermButton` theming layer. `transcoder.py` (~140 lines) is a clean ffmpeg-command builder, a subprocess runner, and a progress/duration parser — no external deps.

---

## 📜 License

Code in this repo: MIT-style, do whatever. ffmpeg itself is **not** MIT — if you distribute a build with `ffmpeg.exe` baked in, the ffmpeg build's license applies to the bundle (typically LGPL for the [gyan.dev essentials](https://www.gyan.dev/ffmpeg/builds/) build). For personal / internal use this is fine; for public redistribution, confirm attribution / source-availability obligations for your chosen ffmpeg build.

---

## 🧇 Credits

Written by Clément Ciuro, with pair-coding help from Claude. Greets to everyone who ever fought with HAP width constraints at 3 AM.
