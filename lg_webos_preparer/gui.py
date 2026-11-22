"""Tkinter Windows GUI; deliberately dependency-free at runtime."""
from __future__ import annotations
import queue
import threading
from pathlib import Path
from .__init__ import __version__ as APP_VERSION
from .models import PROFILES
from .batch import process_folder
from .joblog import CallbackHandler, job_logger
from .ocr import OcrConfig

def gui(*, debug: bool = False, ocr_config: OcrConfig = OcrConfig()) -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f"LG webOS Media Preparer {APP_VERSION}")
    root.geometry("930x690")
    root.minsize(720, 520)
    frm = ttk.Frame(root, padding=14)
    frm.pack(fill="both", expand=True)
    input_var = tk.StringVar()
    output_var = tk.StringVar()
    profile_var = tk.StringVar(value="bx")
    ocr_var = tk.BooleanVar(value=False)
    transcode_var = tk.BooleanVar(value=False)
    debug_var = tk.BooleanVar(value=debug)
    status_var = tk.StringVar(value="Ready. Scan first to see potential compatibility problems.")
    events: queue.Queue[tuple] = queue.Queue()
    busy = [False]

    ttk.Label(frm, text="LG webOS USB Media Preparer", font=("Segoe UI", 17, "bold")).pack(anchor="w")
    ttk.Label(frm, text="Scans video files and makes conservative fixes. Originals are never altered.").pack(anchor="w", pady=(0, 12))

    def path_row(label: str, var: tk.StringVar) -> None:
        f = ttk.Frame(frm)
        f.pack(fill="x", pady=4)
        ttk.Label(f, text=label, width=16).pack(side="left")
        ttk.Entry(f, textvariable=var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        def browse() -> None:
            p = filedialog.askdirectory(title=label)
            if p:
                var.set(p)
                if label == "Input folder" and not output_var.get():
                    output_var.set(str(Path(p).parent / (Path(p).name + "_LG_Ready")))
        ttk.Button(f, text="Browse…", command=browse).pack(side="left")

    path_row("Input folder", input_var)
    path_row("Output folder", output_var)
    pf = ttk.Frame(frm)
    pf.pack(fill="x", pady=(10, 6))
    ttk.Label(pf, text="TV profile", width=16).pack(side="left")
    combo = ttk.Combobox(pf, state="readonly", width=44, values=[f"{k} | {v.title}" for k, v in PROFILES.items()])
    combo.current(0)
    combo.pack(side="left")
    combo.bind("<<ComboboxSelected>>", lambda _: profile_var.set(combo.get().split(" | ")[0]))
    ttk.Label(frm, text="Profiles are cautious estimates, not a guarantee of playback on every firmware.", foreground="#656565").pack(anchor="w", padx=110)

    opt = ttk.LabelFrame(frm, text="Job options", padding=10)
    opt.pack(fill="x", pady=(9, 9))
    ttk.Checkbutton(opt, text="OCR English bitmap subtitles (review text and timing)", variable=ocr_var).pack(anchor="w")
    ttk.Checkbutton(opt, text="Permit H.264 conversion of incompatible SDR video in legacy 1080p mode (slow)", variable=transcode_var).pack(anchor="w", pady=(4, 7))
    ttk.Checkbutton(opt, text="Debug logging", variable=debug_var).pack(anchor="w")

    butt = ttk.Frame(frm)
    butt.pack(fill="x", pady=(0, 9))
    progress_var = tk.DoubleVar(value=0)
    bar = ttk.Progressbar(frm, variable=progress_var, maximum=100)
    bar.pack(fill="x")
    ttk.Label(frm, textvariable=status_var).pack(anchor="w", pady=6)
    log_text = tk.Text(frm, height=18, wrap="word", state="disabled", font=("Consolas", 9))
    log_text.pack(fill="both", expand=True)
    scroll = ttk.Scrollbar(log_text, orient="vertical", command=log_text.yview)
    scroll.pack(side="right", fill="y")
    log_text.configure(yscrollcommand=scroll.set)

    def append_log(s: str) -> None:
        follow = log_text.yview()[1] >= 0.999
        log_text.configure(state="normal")
        log_text.insert("end", s)
        if follow:
            log_text.see("end")
        log_text.configure(state="disabled")

    def poll() -> None:
        log_messages: list[str] = []
        for _ in range(100):
            try:
                e = events.get_nowait()
            except queue.Empty:
                break
            if e[0] == "log":
                log_messages.append(e[1] + "\n")
            elif e[0] == "progress":
                progress_var.set(100 * e[1] / e[2] if e[2] else 0)
                status_var.set(f"Processed {e[1]} of {e[2]} file(s).")
            elif e[0] in {"done", "fatal"}:
                busy[0] = False
                for b in buttons:
                    b.configure(state="normal")
                status_var.set("Finished. See the summary, log and reports."
                               if e[0] == "done" else "Job failed. See the terminal log.")
        if log_messages:
            append_log("".join(log_messages))
        root.after(20 if not events.empty() else 100, poll)

    def start(mode: str) -> None:
        if busy[0]:
            return
        src, dst = Path(input_var.get().strip()), Path(output_var.get().strip())
        if not src.is_dir() or not output_var.get().strip():
            messagebox.showerror("Missing folder", "Select a valid input folder and a different output folder")
            return
        busy[0] = True
        progress_var.set(0)
        for b in buttons:
            b.configure(state="disabled")
        status_var.set(f"{mode.title()} running…")
        opts = dict(input_folder=src, output_folder=dst, profile=PROFILES[profile_var.get()],
                    mode=mode, ocr=ocr_var.get(), allow_sdr_video=transcode_var.get(),
                    seconv=ocr_config.seconv, tesseract=ocr_config.tesseract, tessdata=ocr_config.tessdata)
        logger = job_logger(debug_var.get(), CallbackHandler(lambda msg: events.put(("log", msg))))

        def worker() -> None:
            try:
                process_folder(**opts, logger=logger,
                               progress=lambda a, b: events.put(("progress", a, b)))
                events.put(("done",))
            except Exception:
                events.put(("fatal",))
        threading.Thread(target=worker, daemon=True).start()

    buttons = [ttk.Button(butt, text="1. Scan only", command=lambda: start("scan")),
               ttk.Button(butt, text="2. Prepare LG-ready folder", command=lambda: start("prepare"))]
    for b in buttons:
        b.pack(side="left", padx=(0, 10))
    ttk.Label(butt, text="Preparation copies files; allow ample disk space.", foreground="#666666").pack(side="left")
    root.after(100, poll)
    root.mainloop()


