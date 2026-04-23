"""WaffleEncoder - demoscene/keygen-style HAP & ProRes transcoder."""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, font as tkfont
import tkinter as tk
from tkinter import ttk

from transcoder import CODECS, TranscodeJob, TranscodeOptions, run_ffmpeg

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _HAS_DND = True
except Exception:
    _HAS_DND = False
    TkinterDnD = None  # type: ignore
    DND_FILES = None  # type: ignore

# ─── palette ──────────────────────────────────────────────────────────
BG        = "#06080a"
PANEL     = "#0b1014"
PANEL_HI  = "#10171d"
BORDER    = "#18323a"
BORDER_HI = "#2a5566"
FG        = "#b8d6d6"
FG_DIM    = "#4a6670"
GREEN     = "#55ff99"
GREEN_HI  = "#9dffc6"
CYAN      = "#22d3ee"
CYAN_HI   = "#67e8f9"
MAGENTA   = "#ff4fd8"
MAGENTA_HI= "#ff8ae5"
AMBER     = "#f4c430"
RED       = "#ff5566"
WHITE     = "#eaf2f2"

FONT_FAMILY = "Cascadia Mono"
FONT_FALLBACK = ["Cascadia Code", "Consolas", "Courier New"]

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".mxf", ".webm", ".m4v", ".flv", ".wmv", ".mpg", ".mpeg", ".ts")

# ─── ASCII wordmark (classic 5-row block) ─────────────────────────────
LOGO = r"""
██╗    ██╗ █████╗ ███████╗███████╗██╗     ███████╗
██║    ██║██╔══██╗██╔════╝██╔════╝██║     ██╔════╝
██║ █╗ ██║███████║█████╗  █████╗  ██║     █████╗
██║███╗██║██╔══██║██╔══╝  ██╔══╝  ██║     ██╔══╝
╚███╔███╔╝██║  ██║██║     ██║     ███████╗███████╗
 ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝     ╚═╝     ╚══════╝╚══════╝
"""[1:-1]

SUBLOGO = "  · E · N · C · O · D · E · R ·"

WAFFLE_ICON = [
    "╔══╤══╤══╗",
    "║██│░░│██║",
    "╠══╪══╪══╣",
    "║░░│██│░░║",
    "╠══╪══╪══╣",
    "║██│░░│██║",
    "╚══╧══╧══╝",
]

CREDITS = (
    "[ waffle-encoder.v1 ]  ::  cracked, packed & freshly-toasted by the syrup crew  "
    "::  no dongle · no watermark · hap / prores / divisible-by-four auto-stretch  "
    "::  greets to the midnight muxers, the loop crew, nuke-tools, openfx, and every "
    "poor soul who ever typed `ffmpeg -i foo.mov -c:v hap`  ::  stay crispy  ::  "
)


# ─── helpers ──────────────────────────────────────────────────────────
def find_ffmpeg() -> tuple[str | None, str]:
    """Return (path, source_label).  Prefer the bundled copy when running as exe."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "ffmpeg.exe"
        if bundled.exists():
            return str(bundled), "embedded"

    env = os.environ.get("FFMPEG_BIN")
    if env and Path(env).exists():
        return env, "FFMPEG_BIN"

    here = Path(__file__).parent
    local = here / "ffmpeg.exe"
    if local.exists():
        return str(local), "sibling"

    found = shutil.which("ffmpeg")
    if found:
        return found, "PATH"
    return None, "missing"


def mono(size: int = 10, bold: bool = False) -> tuple:
    return (FONT_FAMILY, size, "bold" if bold else "normal")


def _humanize(n: int) -> str:
    step = 1024.0
    for unit in ("B", "K", "M", "G", "T"):
        if n < step:
            return f"{int(n)}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= step
    return f"{n:.1f}P"


# ─── custom panel (heavy double-line) ────────────────────────────────
class Panel(tk.Frame):
    """Titled panel with double-line header strip: ╔═ TITLE ═══════════╗"""

    def __init__(self, master, title: str, accent: str = CYAN, **kw):
        super().__init__(
            master, bg=PANEL, highlightbackground=BORDER,
            highlightcolor=BORDER, highlightthickness=1, bd=0, **kw,
        )
        self.grid_columnconfigure(0, weight=1)

        head = tk.Frame(self, bg=PANEL)
        head.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 0))
        head.grid_columnconfigure(2, weight=1)
        tk.Label(head, text="╔══", fg=accent, bg=PANEL,
                 font=mono(10, bold=True)).grid(row=0, column=0, sticky="w")
        tk.Label(head, text=f" {title.upper()} ", fg=accent, bg=PANEL,
                 font=mono(10, bold=True)).grid(row=0, column=1, sticky="w")
        tk.Label(head, text="═" * 200, fg=BORDER_HI, bg=PANEL,
                 font=mono(10), anchor="w").grid(row=0, column=2, sticky="ew")

        self.body = tk.Frame(self, bg=PANEL)
        self.body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(6, 12))
        self.body.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)


class TermCheck(tk.Frame):
    """Text-based checkbox: `[x] label` / `[ ] label`.  Click anywhere toggles."""

    def __init__(self, master, text: str, variable: tk.BooleanVar,
                 command=None, color: str = GREEN, **kw):
        super().__init__(master, bg=PANEL, cursor="hand2", **kw)
        self._var = variable
        self._command = command
        self._color = color
        self._enabled = True
        self._box = tk.Label(self, bg=PANEL, font=mono(10, bold=True))
        self._box.grid(row=0, column=0, padx=(0, 8))
        self._label = tk.Label(self, text=text, bg=PANEL, font=mono(10))
        self._label.grid(row=0, column=1, sticky="w")
        for w in (self, self._box, self._label):
            w.bind("<Button-1>", self._on_click)
        self._render()

    def _on_click(self, _):
        if not self._enabled:
            return
        self._var.set(not bool(self._var.get()))
        self._render()
        if self._command:
            self._command()

    def _render(self) -> None:
        checked = bool(self._var.get())
        mark = "[x]" if checked else "[ ]"
        if not self._enabled:
            self._box.configure(text=mark, fg=FG_DIM)
            self._label.configure(fg=FG_DIM)
            cur = "arrow"
        else:
            self._box.configure(text=mark, fg=self._color if checked else FG_DIM)
            self._label.configure(fg=WHITE if checked else FG)
            cur = "hand2"
        for w in (self, self._box, self._label):
            w.configure(cursor=cur)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._render()


class TermButton(tk.Label):
    """Label-as-button with proper hover + disable."""

    def __init__(self, master, text: str, command, color: str = GREEN, big: bool = False, **kw):
        self._color = color
        self._enabled = True
        self._command = command
        super().__init__(
            master, text=text, fg=color, bg=PANEL_HI,
            font=mono(13 if big else 10, bold=True),
            cursor="hand2",
            padx=14 if big else 10, pady=10 if big else 5,
            highlightbackground=BORDER, highlightcolor=BORDER, highlightthickness=1, bd=0,
            **kw,
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _on_enter(self, _):
        if self._enabled:
            self.configure(bg=BORDER, highlightbackground=BORDER_HI, fg=WHITE)

    def _on_leave(self, _):
        if self._enabled:
            self.configure(bg=PANEL_HI, highlightbackground=BORDER, fg=self._color)

    def _on_click(self, _):
        if self._enabled and self._command:
            self._command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if enabled:
            self.configure(fg=self._color, bg=PANEL_HI, cursor="hand2")
        else:
            self.configure(fg=FG_DIM, bg=PANEL, cursor="arrow")


# ─── the app ─────────────────────────────────────────────────────────
_AppBase = TkinterDnD.Tk if _HAS_DND else tk.Tk


class App(_AppBase):  # type: ignore[misc]
    def __init__(self) -> None:
        super().__init__()
        self._resolve_font()
        self.configure(bg=BG)
        self.title("waffle-encoder :: crispy hap/prores keygen")
        self.geometry("1180x860")
        self.minsize(1080, 760)

        self.ffmpeg_path, self.ffmpeg_src = find_ffmpeg()
        self.files: list[Path] = []
        self.output_dir: Path | None = None
        self.msg_queue: queue.Queue = queue.Queue()
        self.stop_flag = threading.Event()
        self.worker: threading.Thread | None = None
        self.current_proc: subprocess.Popen | None = None

        self._cursor_on = True
        self._ticker_idx = 0

        self._build_style()
        self._build_ui()
        self._poll_queue()
        self._blink_cursor()
        self._scroll_ticker()

        self._logln("boot", "waffle-encoder online · all systems nominal", "green")
        if self.ffmpeg_path:
            self._logln("ffmpeg", f"{self.ffmpeg_src.upper()} → {self.ffmpeg_path}", "cyan")
        else:
            self._logln("ffmpeg", "NOT FOUND — set FFMPEG_BIN or place ffmpeg.exe next to the app", "red")
        if _HAS_DND:
            self._logln("dnd", "drag-and-drop armed · drop files or folders anywhere in the window", "magenta")
        else:
            self._logln("dnd", "tkinterdnd2 not available — use the [+ add files] buttons", "amber")
        self._logln("ready", "drop clips · pick a codec · hit the big green button", "dim")

    # ── font / style ─────────────────────────────────────────────
    def _resolve_font(self) -> None:
        global FONT_FAMILY
        fams = set(tkfont.families())
        if FONT_FAMILY not in fams:
            for f in FONT_FALLBACK:
                if f in fams:
                    FONT_FAMILY = f
                    break

    def _build_style(self) -> None:
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(
            "Term.TCombobox",
            fieldbackground=PANEL_HI, background=PANEL_HI, foreground=FG,
            arrowcolor=CYAN, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
            selectbackground=PANEL_HI, selectforeground=FG, padding=4,
        )
        s.map(
            "Term.TCombobox",
            fieldbackground=[("readonly", PANEL_HI), ("disabled", PANEL)],
            foreground=[("disabled", FG_DIM)],
            arrowcolor=[("active", MAGENTA)],
            bordercolor=[("focus", CYAN)],
        )
        self.option_add("*TCombobox*Listbox.background", PANEL_HI)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", MAGENTA)
        self.option_add("*TCombobox*Listbox.selectForeground", BG)
        self.option_add("*TCombobox*Listbox.font", mono(10))
        s.configure(
            "Term.TCheckbutton",
            background=PANEL, foreground=FG,
            indicatorbackground=PANEL_HI,
            bordercolor=BORDER, focuscolor=PANEL, padding=2,
            font=mono(10),
        )
        s.map(
            "Term.TCheckbutton",
            background=[("active", PANEL)],
            foreground=[("active", CYAN_HI), ("disabled", FG_DIM)],
            indicatorcolor=[("selected", GREEN), ("!selected", PANEL_HI)],
        )
        s.configure("Term.Vertical.TScrollbar",
                    background=PANEL, troughcolor=BG, bordercolor=BORDER,
                    arrowcolor=CYAN, gripcount=0)
        s.map("Term.Vertical.TScrollbar",
              background=[("active", BORDER_HI)])

    # ── UI ──────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # ╭── banner ──────────────────────────────────────────────
        banner = tk.Frame(self, bg=BG)
        banner.grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 2))
        banner.grid_columnconfigure(2, weight=1)

        tk.Label(banner, text="\n".join(WAFFLE_ICON), fg=AMBER, bg=BG,
                 font=mono(9, bold=True), justify="left").grid(
            row=0, column=0, rowspan=3, padx=(0, 18), sticky="nw")

        tk.Label(banner, text=LOGO, fg=MAGENTA, bg=BG,
                 font=mono(10, bold=True), justify="left").grid(
            row=0, column=1, sticky="w")
        tk.Label(banner, text=SUBLOGO + "   ✶  demoscene-grade video transcoder", fg=CYAN, bg=BG,
                 font=mono(10, bold=True)).grid(row=1, column=1, sticky="w")

        self.ffmpeg_status = StringVar(value="")
        tk.Label(banner, textvariable=self.ffmpeg_status, fg=FG_DIM, bg=BG,
                 font=mono(9)).grid(row=2, column=1, sticky="w", pady=(2, 0))
        self._update_ffmpeg_status()

        tk.Label(banner, text="//  v1.0", fg=MAGENTA_HI, bg=BG,
                 font=mono(9, bold=True)).grid(row=0, column=2, sticky="ne")
        tk.Label(banner, text="//  hap · hap_q · hap_alpha · prores_ks",
                 fg=FG_DIM, bg=BG, font=mono(9)).grid(row=1, column=2, sticky="ne")

        # horizontal rule with double-line flavour
        tk.Label(self, text="═" * 400, fg=BORDER_HI, bg=BG, font=mono(10), anchor="w").grid(
            row=1, column=0, sticky="ew", padx=20, pady=(8, 10))

        # ╭── body ──────────────────────────────────────────────
        body = tk.Frame(self, bg=BG)
        body.grid(row=2, column=0, sticky="nsew", padx=20)
        body.grid_columnconfigure(0, weight=3, uniform="cols")
        body.grid_columnconfigure(1, weight=2, uniform="cols")
        body.grid_rowconfigure(0, weight=1)

        # left: INPUT
        left = Panel(body, "input.queue", accent=GREEN)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.body.grid_rowconfigure(0, weight=1)
        left.body.grid_columnconfigure(0, weight=1)

        list_wrap = tk.Frame(left.body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        list_wrap.grid(row=0, column=0, columnspan=3, sticky="nsew", pady=(0, 8))
        list_wrap.grid_rowconfigure(0, weight=1)
        list_wrap.grid_columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(
            list_wrap, bg=PANEL_HI, fg=FG, font=mono(10),
            selectbackground=MAGENTA, selectforeground=BG,
            activestyle="none", borderwidth=0, highlightthickness=0,
        )
        self.listbox.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(list_wrap, orient="vertical", command=self.listbox.yview,
                           style="Term.Vertical.TScrollbar")
        sb.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=sb.set)
        self._refresh_file_box()

        # ── drag-and-drop: whole window + listbox both accept drops ──
        if _HAS_DND:
            for widget in (self, self.listbox):
                try:
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<Drop>>", self._on_drop)
                    widget.dnd_bind("<<DropEnter>>", self._on_drop_enter)
                    widget.dnd_bind("<<DropLeave>>", self._on_drop_leave)
                except Exception:
                    pass

        btns = tk.Frame(left.body, bg=PANEL)
        btns.grid(row=1, column=0, columnspan=3, sticky="ew")
        btns.grid_columnconfigure((0, 1, 2), weight=1, uniform="b")
        TermButton(btns, "  ＋ add files  ", self._add_files, color=GREEN).grid(
            row=0, column=0, sticky="ew", padx=(0, 4))
        TermButton(btns, "  ＋ add folder  ", self._add_folder, color=CYAN).grid(
            row=0, column=1, sticky="ew", padx=4)
        TermButton(btns, "  × clear  ", self._clear_files, color=RED).grid(
            row=0, column=2, sticky="ew", padx=(4, 0))

        # right column: options
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.grid_columnconfigure(0, weight=1)

        # VIDEO
        vid = Panel(right, "video.codec", accent=MAGENTA)
        vid.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        vid.body.grid_columnconfigure(1, weight=1)

        self.codec_var = StringVar(value="HAP")
        self._labeled(vid.body, "codec", 0, self._combo(vid.body, self.codec_var,
                      list(CODECS.keys()), self._on_codec_change))

        self.fps_enabled = BooleanVar(value=False)
        self.fps_var = StringVar(value="60")
        fps_row = tk.Frame(vid.body, bg=PANEL)
        fps_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=3)
        fps_row.grid_columnconfigure(1, weight=1)
        TermCheck(fps_row, text="reinterpret fps", variable=self.fps_enabled,
                   command=self._sync_states, color=CYAN).grid(
            row=0, column=0, padx=(0, 8), sticky="w")
        self.fps_entry = self._entry(fps_row, self.fps_var)
        self.fps_entry.grid(row=0, column=1, sticky="ew")

        self.div4_enabled = BooleanVar(value=True)
        self.div4_cb = TermCheck(vid.body, text="force resolution divisible by 4  (hap)",
                                  variable=self.div4_enabled, color=GREEN)
        self.div4_cb.grid(row=2, column=0, columnspan=2, sticky="w", pady=3)

        self.div4_mode = StringVar(value="Nearest (stretch)")
        self.div4_combo = self._combo(vid.body, self.div4_mode,
                                      ["Nearest (stretch)", "Round up (stretch)", "Round down (crop-like)"])
        self._labeled(vid.body, "round", 3, self.div4_combo)

        self.prores_var = StringVar(value="HQ")
        self.prores_combo = self._combo(vid.body, self.prores_var,
                                        ["Proxy", "LT", "Standard", "HQ", "4444", "4444 XQ"])
        self._labeled(vid.body, "prores", 4, self.prores_combo)

        # AUDIO
        aud = Panel(right, "audio.stream", accent=CYAN)
        aud.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        aud.body.grid_columnconfigure(1, weight=1)
        self.audio_enabled = BooleanVar(value=True)
        TermCheck(aud.body, text="keep audio", variable=self.audio_enabled,
                   command=self._sync_states, color=CYAN).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=3)
        self.audio_codec = StringVar(value="pcm_s16le")
        self.audio_combo = self._combo(aud.body, self.audio_codec,
                                       ["pcm_s16le", "pcm_s24le", "aac", "copy"])
        self._labeled(aud.body, "codec", 1, self.audio_combo)

        # OUTPUT
        out = Panel(right, "output.target", accent=AMBER)
        out.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        out.body.grid_columnconfigure(1, weight=1)
        self.out_label_var = StringVar(value="(same as input)")
        self._labeled(out.body, "folder", 0,
                      tk.Label(out.body, textvariable=self.out_label_var, fg=FG_DIM, bg=PANEL,
                               font=mono(10), anchor="w"))
        TermButton(out.body, "  … choose folder  ", self._choose_output, color=AMBER).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(2, 6))
        self.suffix_var = StringVar(value="")
        self._labeled(out.body, "suffix", 2, self._entry(out.body, self.suffix_var))

        # ╭── LOG ──
        logp = Panel(self, "tx.log  >_", accent=GREEN)
        logp.grid(row=3, column=0, sticky="nsew", padx=20, pady=(10, 8))
        self.grid_rowconfigure(3, weight=1)
        logp.body.grid_columnconfigure(0, weight=1)
        logp.body.grid_rowconfigure(0, weight=1)

        log_wrap = tk.Frame(logp.body, bg=PANEL_HI, highlightbackground=BORDER, highlightthickness=1)
        log_wrap.grid(row=0, column=0, sticky="nsew")
        log_wrap.grid_rowconfigure(0, weight=1)
        log_wrap.grid_columnconfigure(0, weight=1)
        self.log = tk.Text(
            log_wrap, bg=PANEL_HI, fg=FG, font=mono(10), wrap="word",
            borderwidth=0, highlightthickness=0, insertbackground=GREEN,
            padx=10, pady=8,
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        sb2 = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log.yview,
                            style="Term.Vertical.TScrollbar")
        sb2.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=sb2.set)
        self.log.tag_configure("green",   foreground=GREEN_HI)
        self.log.tag_configure("cyan",    foreground=CYAN_HI)
        self.log.tag_configure("magenta", foreground=MAGENTA_HI)
        self.log.tag_configure("amber",   foreground=AMBER)
        self.log.tag_configure("red",     foreground=RED)
        self.log.tag_configure("dim",     foreground=FG_DIM)
        self.log.tag_configure("cursor",  foreground=GREEN, background=GREEN)
        self.log.configure(state="disabled")

        # ╭── status ──
        statp = Panel(self, "status.engine", accent=MAGENTA)
        statp.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 8))
        statp.body.grid_columnconfigure(0, weight=1)

        self.progress_var = StringVar(value=self._render_bar(0.0))
        tk.Label(statp.body, textvariable=self.progress_var,
                 fg=GREEN_HI, bg=PANEL, font=mono(12, bold=True), anchor="w").grid(
            row=0, column=0, sticky="ew", pady=(0, 4))

        self.status_var = StringVar(value="⏾  idle · awaiting input")
        tk.Label(statp.body, textvariable=self.status_var,
                 fg=CYAN, bg=PANEL, font=mono(10), anchor="w").grid(
            row=1, column=0, sticky="ew", pady=(0, 10))

        actions = tk.Frame(statp.body, bg=PANEL)
        actions.grid(row=2, column=0, sticky="ew")
        actions.grid_columnconfigure((0, 1), weight=1, uniform="a")
        self.start_btn = TermButton(actions, "  ▶  START TRANSCODING  ",
                                     self._start, color=GREEN, big=True)
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.cancel_btn = TermButton(actions, "  ■  CANCEL  ",
                                      self._cancel, color=RED, big=True)
        self.cancel_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.cancel_btn.set_enabled(False)

        # ╭── credits ticker ──
        ticker_frame = tk.Frame(self, bg=BG)
        ticker_frame.grid(row=5, column=0, sticky="ew", padx=20, pady=(0, 10))
        ticker_frame.grid_columnconfigure(0, weight=1)
        self.ticker_var = StringVar(value="")
        tk.Label(ticker_frame, textvariable=self.ticker_var, fg=FG_DIM, bg=BG,
                 font=mono(9), anchor="w").grid(row=0, column=0, sticky="ew")

        self._on_codec_change()
        self._sync_states()

    # ── helpers ────────────────────────────────────────────────
    def _labeled(self, parent, label, row, widget):
        tk.Label(parent, text=f"› {label:<8}", fg=FG_DIM, bg=PANEL,
                 font=mono(10), anchor="w").grid(row=row, column=0, sticky="w",
                                                  pady=3, padx=(0, 10))
        widget.grid(row=row, column=1, sticky="ew", pady=3)

    def _combo(self, parent, var, values, cmd=None):
        cb = ttk.Combobox(parent, textvariable=var, values=values, state="readonly",
                          style="Term.TCombobox", font=mono(10))
        if cmd is not None:
            cb.bind("<<ComboboxSelected>>", lambda _e: cmd())
        return cb

    def _entry(self, parent, var):
        return tk.Entry(
            parent, textvariable=var, bg=PANEL_HI, fg=FG, font=mono(10),
            relief="flat", insertbackground=GREEN, disabledbackground=PANEL,
            disabledforeground=FG_DIM,
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=CYAN,
        )

    def _render_bar(self, pct: float, width: int = 52) -> str:
        pct = max(0.0, min(1.0, pct))
        filled = int(pct * width)
        bar = "█" * filled + "▓" + "░" * max(0, width - filled - 1) if filled < width else "█" * width
        return f"[{bar}]  {int(pct * 100):3d}%"

    def _update_ffmpeg_status(self) -> None:
        if self.ffmpeg_path:
            short = (self.ffmpeg_path[:54] + "…") if len(self.ffmpeg_path) > 55 else self.ffmpeg_path
            self.ffmpeg_status.set(f"// ffmpeg: [{self.ffmpeg_src.upper()}]  {short}")
        else:
            self.ffmpeg_status.set("// ffmpeg: MISSING")

    def _logln(self, tag: str, msg: str, color: str = "green") -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"[{tag:<6}] ", "cyan")
        self.log.insert("end", msg + "\n", color)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _lograw(self, text: str, color: str = "dim") -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text, color)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _blink_cursor(self) -> None:
        # blinking "▓" at the end of the status line when idle
        mark = "▓" if self._cursor_on else " "
        current = self.status_var.get().rstrip("▓ ")
        self.status_var.set(current + "  " + mark)
        self._cursor_on = not self._cursor_on
        self.after(550, self._blink_cursor)

    def _scroll_ticker(self) -> None:
        window = 160
        pad = CREDITS + "     "
        n = len(pad)
        seg = (pad * 3)[self._ticker_idx:self._ticker_idx + window]
        self.ticker_var.set(seg)
        self._ticker_idx = (self._ticker_idx + 1) % n
        self.after(120, self._scroll_ticker)

    # ── handlers ────────────────────────────────────────────────
    def _on_codec_change(self) -> None:
        codec = self.codec_var.get()
        is_hap = codec.startswith("HAP")
        is_prores = codec.startswith("ProRes")
        self.div4_cb.set_enabled(is_hap)
        self.div4_combo.configure(state=("readonly" if is_hap else "disabled"))
        self.prores_combo.configure(state=("readonly" if is_prores else "disabled"))

    def _sync_states(self) -> None:
        self.fps_entry.configure(state=("normal" if self.fps_enabled.get() else "disabled"))
        self.audio_combo.configure(state=("readonly" if self.audio_enabled.get() else "disabled"))

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="add files",
            filetypes=[("video", " ".join(f"*{e}" for e in VIDEO_EXTS)), ("all", "*.*")],
        )
        for p in paths:
            self._add_path(Path(p))
        self._refresh_file_box()
        if paths:
            self._logln("queue", f"+ {len(paths)} file(s)", "green")

    # ── drag-and-drop ──────────────────────────────────────────
    def _on_drop(self, event) -> None:
        try:
            raw = self.tk.splitlist(event.data)
        except Exception:
            raw = [event.data]
        added = 0
        skipped_non_video = 0
        for raw_path in raw:
            p = Path(raw_path)
            if p.is_file():
                if p.suffix.lower() in VIDEO_EXTS:
                    if p not in self.files:
                        self.files.append(p)
                        added += 1
                else:
                    skipped_non_video += 1
            elif p.is_dir():
                for sub in sorted(p.rglob("*")):
                    if sub.is_file() and sub.suffix.lower() in VIDEO_EXTS and sub not in self.files:
                        self.files.append(sub)
                        added += 1
        self._refresh_file_box()
        self._on_drop_leave(None)
        if added:
            self._logln("drop", f"+ {added} file(s) via drag-and-drop", "green")
        if skipped_non_video and not added:
            self._logln("drop", f"ignored {skipped_non_video} non-video file(s)", "amber")

    def _on_drop_enter(self, _event) -> None:
        self.configure(bg=BORDER)
        self.status_var.set("◎  drop to enqueue…")

    def _on_drop_leave(self, _event) -> None:
        self.configure(bg=BG)

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory(title="add folder")
        if not folder:
            return
        root = Path(folder)
        before = len(self.files)
        for p in sorted(root.rglob("*")):
            if p.suffix.lower() in VIDEO_EXTS and p.is_file():
                self._add_path(p)
        self._refresh_file_box()
        self._logln("scan", f"{folder} — added {len(self.files) - before} clips", "cyan")

    def _add_path(self, path: Path) -> None:
        if path not in self.files:
            self.files.append(path)

    def _clear_files(self) -> None:
        n = len(self.files)
        self.files.clear()
        self._refresh_file_box()
        if n:
            self._logln("queue", f"cleared {n} file(s)", "amber")

    def _refresh_file_box(self) -> None:
        self.listbox.delete(0, "end")
        if not self.files:
            hint = "  ░░  queue empty · drag & drop files or folders here · or hit [+ add files]  ░░"
            self.listbox.insert("end", hint)
            self.listbox.itemconfig(0, foreground=FG_DIM)
            return
        for i, p in enumerate(self.files):
            try:
                size_str = _humanize(p.stat().st_size)
            except OSError:
                size_str = "?"
            self.listbox.insert("end", f"  {i + 1:>3}│ {p.name:<48} {size_str:>10}  · {p.parent}")

    def _choose_output(self) -> None:
        folder = filedialog.askdirectory(title="output folder")
        if folder:
            self.output_dir = Path(folder)
            self.out_label_var.set(str(self.output_dir))

    # ── run ────────────────────────────────────────────────────
    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.ffmpeg_path:
            self._logln("err", "ffmpeg not found — install it or bundle ffmpeg.exe", "red")
            return
        if not self.files:
            self._logln("err", "queue is empty", "amber")
            return

        fps = None
        if self.fps_enabled.get():
            try:
                fps = float(self.fps_var.get())
                if fps <= 0:
                    raise ValueError
            except ValueError:
                self._logln("err", f"invalid fps: {self.fps_var.get()!r}", "red")
                return

        codec_key = self.codec_var.get()
        suffix = self.suffix_var.get().strip() or ("_hap" if codec_key.startswith("HAP") else "_prores")

        mode_map = {
            "Nearest (stretch)": "nearest",
            "Round up (stretch)": "up",
            "Round down (crop-like)": "down",
        }

        options = TranscodeOptions(
            codec_key=codec_key,
            prores_profile=self.prores_var.get(),
            fps=fps,
            force_div4=self.div4_enabled.get() and codec_key.startswith("HAP"),
            div4_mode=mode_map[self.div4_mode.get()],
            audio_enabled=self.audio_enabled.get(),
            audio_codec=self.audio_codec.get(),
            suffix=suffix,
        )

        jobs: list[TranscodeJob] = []
        for f in self.files:
            out_dir = self.output_dir if self.output_dir else f.parent
            ext = CODECS[codec_key]["ext"]
            out = out_dir / f"{f.stem}{suffix}{ext}"
            jobs.append(TranscodeJob(src=f, dst=out))

        self.stop_flag.clear()
        self.start_btn.set_enabled(False)
        self.cancel_btn.set_enabled(True)
        self._logln("start", f"queue={len(jobs)}  codec={codec_key}  suffix={suffix}", "magenta")
        self.worker = threading.Thread(target=self._run_jobs, args=(jobs, options), daemon=True)
        self.worker.start()

    def _run_jobs(self, jobs: list[TranscodeJob], options: TranscodeOptions) -> None:
        total = len(jobs)
        for idx, job in enumerate(jobs, 1):
            if self.stop_flag.is_set():
                self.msg_queue.put(("log", ("cancel", f"skipped: {job.src.name}", "amber")))
                break
            self.msg_queue.put(("status", f"►  [{idx}/{total}]  {job.src.name}"))
            self.msg_queue.put(("log", ("job", f"{idx}/{total}  {job.src.name}  →  {job.dst}", "magenta")))
            try:
                for event in run_ffmpeg(self.ffmpeg_path, job, options, self.stop_flag, self._register_proc):
                    kind, payload = event
                    if kind == "progress" and isinstance(payload, float):
                        overall = ((idx - 1) + payload) / total
                        self.msg_queue.put(("progress", overall))
                    elif kind == "log":
                        self.msg_queue.put(("logRaw", str(payload)))
                    elif kind == "done":
                        ok = bool(payload)
                        self.msg_queue.put(("log", ("done", "OK — wrote " + str(job.dst) if ok else "FAILED",
                                                    "green" if ok else "red")))
            except Exception as e:  # pragma: no cover
                self.msg_queue.put(("log", ("err", str(e), "red")))
        self.msg_queue.put(("finish", None))

    def _register_proc(self, proc: subprocess.Popen | None) -> None:
        self.current_proc = proc

    def _cancel(self) -> None:
        self.stop_flag.set()
        if self.current_proc and self.current_proc.poll() is None:
            try:
                self.current_proc.terminate()
            except Exception:
                pass
        self._logln("cancel", "halting…", "amber")

    # ── queue pump ─────────────────────────────────────────────
    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "logRaw":
                    self._lograw(str(payload), "dim")
                elif kind == "log" and isinstance(payload, tuple) and len(payload) == 3:
                    t, msg, color = payload
                    self._logln(t, msg, color=color)
                elif kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "progress" and isinstance(payload, float):
                    self.progress_var.set(self._render_bar(payload))
                elif kind == "finish":
                    self.progress_var.set(self._render_bar(1.0))
                    self.status_var.set("✓  done.")
                    self.start_btn.set_enabled(True)
                    self.cancel_btn.set_enabled(False)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
