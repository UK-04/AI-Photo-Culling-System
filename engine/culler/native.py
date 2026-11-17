"""Native macOS open dialogs, for when the UI runs in a browser.

A web page cannot learn the real path of a folder the user picks, but the engine runs
on the same Mac, so it asks Finder directly (through ``osascript``, which ships with
macOS). The desktop app does not use this: it has its own native dialogs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

_ACTIVATE = ["try", "tell me to activate", "end try"]  # bring the dialog to the front


class DialogUnavailable(Exception):
    """Not on macOS (or osascript is missing)."""


class DialogError(Exception):
    pass


def available() -> bool:
    return sys.platform == "darwin" and shutil.which("osascript") is not None


def _osascript(lines: list[str]) -> str | None:
    """Run AppleScript lines. Returns its output, or ``None`` if the user cancelled."""
    if not available():
        raise DialogUnavailable("Native dialogs need macOS")
    args = ["osascript"]
    for line in lines:
        args += ["-e", line]
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        if "-128" in proc.stderr or "User canceled" in proc.stderr:
            return None
        raise DialogError(proc.stderr.strip() or "The dialog could not be shown")
    return proc.stdout


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def pick_folder(prompt: str = "Choose a folder of photos") -> str | None:
    out = _osascript([*_ACTIVATE, f"POSIX path of (choose folder with prompt {_quote(prompt)})"])
    if out is None:
        return None
    path = out.strip()
    return path.rstrip("/") or "/" if path else None


def pick_files(prompt: str = "Select photos") -> list[str]:
    out = _osascript([
        *_ACTIVATE,
        f"set chosen to choose file with prompt {_quote(prompt)} with multiple selections allowed",
        'set out to ""',
        "repeat with f in chosen",
        "set out to out & POSIX path of (contents of f) & linefeed",
        "end repeat",
        "out",
    ])
    if out is None:
        return []
    return [line for line in out.splitlines() if line.strip()]
