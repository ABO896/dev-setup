#!/usr/bin/env python3
"""Install this repo's files on macOS or Windows.

  python3 install.py        (Mac)
  python install.py         (Windows, in PowerShell 7)

What it does:
  - ~/.local/bin/new-cpp     -> repo/new-cpp
  - Zed's global tasks.json  -> repo/zed/tasks.mac.json   (Mac: symlink)
                                repo/zed/tasks.windows.json (Windows: written with your
                                user folder filled in)

It never touches Zed's settings.json. Any file it replaces is first renamed to
*.bak-<timestamp>, never deleted.

Mac: symlinks, so `git pull` updates everything at once.
Windows: the tasks file is generated, and new-cpp is a symlink only with Developer
Mode on (otherwise a copy). Re-run this script after `git pull`.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
SYSTEM = platform.system()


def zed_config_dir() -> Path:
    if SYSTEM == "Windows":
        return Path(os.environ["APPDATA"]) / "Zed"
    return Path.home() / ".config" / "zed"   # macOS and Linux


def backup(dest: Path) -> None:
    if dest.exists() or dest.is_symlink():
        bak = dest.with_name(f"{dest.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        dest.rename(bak)
        print(f"  ~ kept your old {dest.name} as {bak.name}")


def link(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink() and dest.resolve() == src.resolve():
        print(f"  = {dest} (already linked)")
        return
    backup(dest)
    try:
        dest.symlink_to(src)
        print(f"  + {dest} -> {src}")
    except OSError:
        shutil.copy2(src, dest)
        print(f"  + {dest} (copied: re-run install.py after each git pull)")


def render(src: Path, dest: Path, replacements: dict[str, str]) -> None:
    text = src.read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(key, value)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not dest.is_symlink() and dest.read_text(encoding="utf-8") == text:
        print(f"  = {dest} (up to date)")
        return
    backup(dest)
    dest.write_text(text, encoding="utf-8")
    print(f"  + {dest} (generated)")


def main() -> int:
    if SYSTEM not in ("Darwin", "Windows", "Linux"):
        print(f"Unsupported OS: {SYSTEM}")
        return 1

    print(f"Installing from {REPO}")
    link(REPO / "new-cpp", Path.home() / ".local" / "bin" / "new-cpp")
    if SYSTEM == "Windows":
        home = Path.home().as_posix()          # e.g. C:/Users/Alvaro
        render(REPO / "zed" / "tasks.windows.json", zed_config_dir() / "tasks.json",
               {"__HOME__": home})
    else:
        os.chmod(REPO / "new-cpp", 0o755)
        link(REPO / "zed" / "tasks.mac.json", zed_config_dir() / "tasks.json")

    print("\nDone. Zed's settings.json was not touched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
