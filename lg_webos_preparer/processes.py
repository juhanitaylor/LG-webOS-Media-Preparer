"""Headless subprocess execution, with optional streaming diagnostics."""
from __future__ import annotations

import logging
import queue
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

from .models import MediaError


OPTIONS = {
    "stdin": subprocess.DEVNULL,
    "text": True,
    "encoding": "utf-8",
    "errors": "replace",
    "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
}


def cmd_run(args: list[str], *, capture: bool = True, timeout: float | None = None,
            env: dict[str, str] | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(args, **OPTIONS, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                                stderr=subprocess.PIPE, timeout=timeout, env=env, cwd=cwd, check=False)
    except OSError as exc:
        raise MediaError(f"Could not start {Path(args[0]).name}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{Path(args[0]).name} timed out after {timeout:g} seconds") from exc
    if result.returncode:
        error = (result.stderr or result.stdout or "Unknown error").strip()
        raise MediaError(f"{Path(args[0]).name} failed ({result.returncode}): {error[-1400:]}")
    return result


def stream_command(args: list[str], logger: logging.Logger, stdout_line: Callable[[str], None], *,
                   label: str, env: dict[str, str] | None = None, cwd: Path | None = None,
                   timeout: float | None = None) -> None:
    logger.debug("%s command: %r", label, args)
    try:
        proc = subprocess.Popen(args, **OPTIONS, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=env, cwd=cwd)
    except OSError as exc:
        raise MediaError(f"Could not start {label}: {exc}") from exc

    lines: queue.Queue[tuple[bool, str | None]] = queue.Queue(maxsize=512)
    stop = threading.Event()

    def enqueue(item: tuple[bool, str | None]) -> None:
        while not stop.is_set():
            try:
                lines.put(item, timeout=0.1)
                return
            except queue.Full:
                continue

    def read(pipe, diagnostic: bool) -> None:
        try:
            with pipe:
                for line in pipe:
                    if stop.is_set():
                        break
                    enqueue((diagnostic, line.strip()))
        finally:
            enqueue((diagnostic, None))

    for pipe, diagnostic in ((proc.stdout, False), (proc.stderr, True)):
        threading.Thread(target=read, args=(pipe, diagnostic), daemon=True).start()

    deadline = time.monotonic() + timeout if timeout is not None else None
    tail: deque[str] = deque(maxlen=8)
    diagnostics: deque[str] = deque(maxlen=8)
    seen: set[str] = set()
    suppressed = 0
    open_pipes = 2
    try:
        while open_pipes:
            remaining = deadline - time.monotonic() if deadline is not None else None
            if remaining is not None and remaining <= 0:
                raise MediaError(f"{label} timed out after {timeout:g} seconds")
            try:
                diagnostic, line = lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise MediaError(f"{label} timed out after {timeout:g} seconds") from exc
            if line is None:
                open_pipes -= 1
            elif line and not diagnostic:
                stdout_line(line)
                tail.append(line)
            elif line:
                diagnostics.append(line)
                if line in seen or len(seen) >= 12:
                    suppressed += 1
                else:
                    seen.add(line)
                    level = logging.ERROR if "[error]" in line.lower() or "[fatal]" in line.lower() else logging.WARNING
                    logger.log(level, "  %s: %s", label, line)
        try:
            remaining = max(0, deadline - time.monotonic()) if deadline is not None else None
            code = proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise MediaError(f"{label} timed out after {timeout:g} seconds") from exc
    finally:
        stop.set()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    if suppressed:
        logger.warning("  %s: suppressed %d repeated or additional diagnostic line(s)", label, suppressed)
    if code:
        error = " | ".join(diagnostics or tail)[-1800:]
        raise MediaError(f"{label} failed ({code}): {error or 'no diagnostic output'}")


def run_ffmpeg(args: list[str], ffmpeg: str = "ffmpeg", *, logger: logging.Logger | None = None,
               duration: float = 0, operation: str = "FFmpeg") -> None:
    logger = logger if logger is not None else logging.getLogger(__name__)
    progress: dict[str, str] = {}
    last_update = time.monotonic()

    def update(line: str) -> None:
        nonlocal last_update
        key, separator, value = line.partition("=")
        if not separator:
            logger.debug("  %s: %s", operation, line)
            return
        progress[key] = value
        if key != "progress":
            return
        now = time.monotonic()
        if value == "end" or now - last_update >= 5:
            elapsed = progress.get("out_time", "unknown")
            elapsed_us = progress.get("out_time_us", "")
            percent = ""
            if value != "end" and duration > 0 and elapsed_us.lstrip("-").isdigit():
                percent = f", {min(100.0, max(0.0, int(elapsed_us) / (duration * 10000))):.0f}%"
            logger.info("  %s %s | media time %s%s | speed %s", operation,
                        "final progress" if value == "end" else "progress", elapsed, percent,
                        progress.get("speed", "").strip() or "unknown")
            last_update = now
        progress.clear()

    stream_command([ffmpeg, "-hide_banner", "-loglevel", "level+warning", "-nostdin", "-n", "-nostats",
                    "-stats_period", "2", "-progress", "pipe:1", *args],
                   logger, update, label=operation)
