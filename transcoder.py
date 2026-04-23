"""ffmpeg command builder and runner for HAP / ProRes."""
from __future__ import annotations

import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generator, Iterable

# Codec registry. ext is the container we write.
CODECS: dict[str, dict] = {
    "HAP":       {"vcodec": "hap", "fmt": None,         "ext": ".mov", "pix_fmt": None},
    "HAP Alpha": {"vcodec": "hap", "fmt": "hap_alpha",  "ext": ".mov", "pix_fmt": None},
    "HAP Q":     {"vcodec": "hap", "fmt": "hap_q",      "ext": ".mov", "pix_fmt": None},
    "ProRes Proxy":    {"vcodec": "prores_ks", "profile": 0, "ext": ".mov", "pix_fmt": "yuv422p10le"},
    "ProRes LT":       {"vcodec": "prores_ks", "profile": 1, "ext": ".mov", "pix_fmt": "yuv422p10le"},
    "ProRes Standard": {"vcodec": "prores_ks", "profile": 2, "ext": ".mov", "pix_fmt": "yuv422p10le"},
    "ProRes HQ":       {"vcodec": "prores_ks", "profile": 3, "ext": ".mov", "pix_fmt": "yuv422p10le"},
    "ProRes 4444":     {"vcodec": "prores_ks", "profile": 4, "ext": ".mov", "pix_fmt": "yuva444p10le"},
    "ProRes 4444 XQ":  {"vcodec": "prores_ks", "profile": 5, "ext": ".mov", "pix_fmt": "yuva444p10le"},
}

PRORES_PROFILE_MAP = {"Proxy": 0, "LT": 1, "Standard": 2, "HQ": 3, "4444": 4, "4444 XQ": 5}


@dataclass
class TranscodeOptions:
    codec_key: str
    prores_profile: str = "HQ"
    fps: float | None = None
    force_div4: bool = True
    div4_mode: str = "nearest"   # nearest | up | down
    audio_enabled: bool = True
    audio_codec: str = "pcm_s16le"
    suffix: str = ""


@dataclass
class TranscodeJob:
    src: Path
    dst: Path


def _div4_expr(mode: str) -> str:
    if mode == "up":
        return "scale=trunc((iw+3)/4)*4:trunc((ih+3)/4)*4"
    if mode == "down":
        return "scale=trunc(iw/4)*4:trunc(ih/4)*4"
    # nearest: stretch to closest multiple of 4
    return "scale=trunc((iw+2)/4)*4:trunc((ih+2)/4)*4"


def build_cmd(ffmpeg: str, job: TranscodeJob, opts: TranscodeOptions) -> list[str]:
    codec_def = CODECS[opts.codec_key]
    vfilters: list[str] = []

    if opts.force_div4 and opts.codec_key.startswith("HAP"):
        vfilters.append(_div4_expr(opts.div4_mode))

    cmd: list[str] = [ffmpeg, "-hide_banner", "-y"]

    # Reinterpret frame rate: same frames, new rate => the output is longer/shorter.
    # This is done with -r BEFORE -i (as an input option), so ffmpeg ignores the
    # container's declared fps and stamps each frame at the new rate.
    if opts.fps:
        cmd += ["-r", f"{opts.fps:g}"]

    cmd += ["-i", str(job.src)]

    # Video
    cmd += ["-c:v", codec_def["vcodec"]]
    if codec_def["vcodec"] == "hap" and codec_def.get("fmt"):
        cmd += ["-format", codec_def["fmt"]]
    if codec_def["vcodec"] == "prores_ks":
        profile = PRORES_PROFILE_MAP.get(opts.prores_profile, 3)
        cmd += ["-profile:v", str(profile), "-vendor", "apl0"]
    if codec_def.get("pix_fmt"):
        cmd += ["-pix_fmt", codec_def["pix_fmt"]]

    if vfilters:
        cmd += ["-vf", ",".join(vfilters)]

    # Audio
    if opts.audio_enabled:
        if opts.audio_codec == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", opts.audio_codec]
            if opts.audio_codec == "aac":
                cmd += ["-b:a", "192k"]
    else:
        cmd += ["-an"]

    # Progress to stderr parsing works; also ask for progress to be verbose
    cmd += ["-stats", str(job.dst)]
    return cmd


DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def _hms_to_s(h: str, m: str, s: str) -> float:
    return int(h) * 3600 + int(m) * 60 + float(s)


def run_ffmpeg(
    ffmpeg: str,
    job: TranscodeJob,
    opts: TranscodeOptions,
    stop_flag: threading.Event,
    register_proc: Callable[[subprocess.Popen | None], None],
) -> Generator[tuple[str, object], None, None]:
    job.dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_cmd(ffmpeg, job, opts)
    yield ("log", "CMD: " + " ".join(_quote(a) for a in cmd) + "\n")

    creationflags = 0
    try:
        import subprocess as _sp
        creationflags = getattr(_sp, "CREATE_NO_WINDOW", 0)
    except Exception:
        pass

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        universal_newlines=True,
        creationflags=creationflags,
    )
    register_proc(proc)

    duration: float | None = None
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if stop_flag.is_set():
                proc.terminate()
                break
            line = line.rstrip("\r\n")
            if not line:
                continue

            if duration is None:
                m = DURATION_RE.search(line)
                if m:
                    duration = _hms_to_s(*m.groups())
                    yield ("log", f"duration={duration:.2f}s\n")

            m = TIME_RE.search(line)
            if m and duration:
                t = _hms_to_s(*m.groups())
                pct = max(0.0, min(1.0, t / duration))
                yield ("progress", pct)
                yield ("log", _compact_stat_line(line) + "\n")
            else:
                # Skip blank verbose lines, log meaningful ones
                if _is_interesting(line):
                    yield ("log", line + "\n")
    finally:
        code = proc.wait()
        register_proc(None)

    ok = code == 0 and not stop_flag.is_set()
    yield ("done", ok)


def _is_interesting(line: str) -> bool:
    lower = line.lower()
    keys = ("error", "invalid", "warning", "stream", "input #", "output #", "video:", "audio:")
    return any(k in lower for k in keys)


def _compact_stat_line(line: str) -> str:
    # Extract only the useful bits from a long ffmpeg progress line
    parts = []
    for key in ("frame", "fps", "time", "bitrate", "speed"):
        m = re.search(rf"{key}=\s*([^\s]+)", line)
        if m:
            parts.append(f"{key}={m.group(1)}")
    return " ".join(parts) if parts else line


def _quote(arg: str) -> str:
    if " " in arg or '"' in arg:
        return '"' + arg.replace('"', '\\"') + '"'
    return arg
