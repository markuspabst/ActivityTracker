"""
Linux platform implementation for ActivityTracker.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

from platform_layer import PlatformABC


APP_NAME = "ActivityTracker"

# Autostart via XDG Desktop Specification
AUTOSTART_DIR = Path(os.path.expanduser("~/.config/autostart"))
DESKTOP_FILE = AUTOSTART_DIR / "activitytracker.desktop"


class LinuxPlatform(PlatformABC):

    _idle_cache: dict = {"time": 0.0, "value": 0.0}
    IDLE_CACHE_TTL: float = 1.0

    # ── Idle detection ──────────────────────────────────────
    # Tries python-xlib first, then xprintidle command, then logind.

    def get_idle_time(self) -> float:
        now = time.time()
        if now - self._idle_cache["time"] < self.IDLE_CACHE_TTL:
            return self._idle_cache["value"]

        value = 0.0

        # Method 1: X11 screensaver extension (requires python-xlib)
        try:
            from Xlib import display
            from Xlib.ext import screensaver
            d = display.Display()
            info = screensaver.Info(d, d.screen().root)
            value = info.idle / 1000.0
        except (ImportError, AttributeError):
            # Method 2: xprintidle command
            try:
                value = int(
                    subprocess.check_output(["xprintidle"]).decode()
                ) / 1000.0
            except (FileNotFoundError, ValueError, subprocess.CalledProcessError):
                # Method 3: logind via dbus (Wayland)
                try:
                    output = subprocess.check_output(
                        ["loginctl", "show-session", "$(loginctl | grep $(whoami) | awk '{print $1}' | head -1)", "-p", "IdleSinceHint"],
                        shell=True, stderr=subprocess.DEVNULL,
                    ).decode().strip()
                    if "=" in output:
                        idle_since = int(output.split("=")[1])
                        value = (time.time() * 1_000_000 - idle_since) / 1_000_000
                        value = max(value, 0.0)
                except Exception:
                    value = 0.0

        self._idle_cache.update(time=now, value=value)
        return value

    # ── App bundle / version info ───────────────────────────

    def get_bundle_version(self, fallback: str = "dev") -> str:
        return fallback

    def get_bundle_build_date(self, fallback: str = "dev") -> str:
        return fallback

    # ── Dialogs ─────────────────────────────────────────────

    @staticmethod
    def _has_command(cmd: str) -> bool:
        return subprocess.run(
            ["which", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode == 0

    def ask_slider_dialog(
        self, title: str, current: float,
        min_value: float = 0, max_value: float = 100,
    ) -> Optional[float]:
        if self._has_command("zenity"):
            proc = subprocess.run(
                [
                    "zenity", "--entry",
                    f"--title={title}",
                    f"--text={title}",
                    f"--entry-text={current:.1f}",
                ],
                capture_output=True, text=True, check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                try:
                    return max(min(float(proc.stdout.strip()), max_value), min_value)
                except ValueError:
                    return None
        elif self._has_command("kdialog"):
            proc = subprocess.run(
                [
                    "kdialog", "--title", title,
                    "--inputbox", title, f"{current:.1f}",
                ],
                capture_output=True, text=True, check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                try:
                    return max(min(float(proc.stdout.strip()), max_value), min_value)
                except ValueError:
                    return None
        return None

    def choose_folder_dialog(self, prompt: str = "") -> Optional[str]:
        if self._has_command("zenity"):
            proc = subprocess.run(
                ["zenity", "--file-selection", "--directory"] +
                (["--title", prompt] if prompt else []),
                capture_output=True, text=True, check=False,
            )
            return proc.stdout.strip() if proc.returncode == 0 else None
        elif self._has_command("kdialog"):
            proc = subprocess.run(
                ["kdialog", "--getexistingdirectory"] +
                (["--title", prompt] if prompt else []),
                capture_output=True, text=True, check=False,
            )
            return proc.stdout.strip() if proc.returncode == 0 else None
        return None

    # ── Autostart (XDG autostart .desktop file) ─────────────

    def _ensure_desktop_file(self) -> Path:
        AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)

        exe = sys.executable

        desktop_content = (
            "[Desktop Entry]\n"
            f"Name={APP_NAME}\n"
            "Type=Application\n"
            f"Exec={exe} {Path(__file__).resolve().parent.parent / 'activity_tracker_menu.py'}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        DESKTOP_FILE.write_text(desktop_content)
        DESKTOP_FILE.chmod(0o755)
        return DESKTOP_FILE

    def autostart_installed(self) -> bool:
        return DESKTOP_FILE.exists()

    def autostart_loaded(self) -> bool:
        return self.autostart_installed()

    def install_autostart(self) -> None:
        self._ensure_desktop_file()

    def uninstall_autostart(self) -> None:
        if DESKTOP_FILE.exists():
            DESKTOP_FILE.unlink()

    # ── File manager ────────────────────────────────────────

    def open_file_manager(self, path: str) -> None:
        subprocess.run(["xdg-open", path])

    def reveal_file_in_manager(self, path: str) -> None:
        subprocess.run(["xdg-open", os.path.dirname(path)])

    # ── Autostart config path ────────────────────────────

    def get_autostart_config_path(self) -> Optional[Tuple[str, str]]:
        return (str(AUTOSTART_DIR), str(DESKTOP_FILE))

    # ── Dashboard scripting ─────────────────────────────────

    def find_dashboard_script(self) -> Path:
        return Path(__file__).resolve().parent.parent / "scripts" / "generate_dashboard.py"

    # ── Locale helpers ──────────────────────────────────────

    def get_system_locale(self) -> Optional[str]:
        for env_var in ("LC_ALL", "LANGUAGE", "LANG"):
            value = os.environ.get(env_var)
            if value:
                lang = value.split(".")[0].split("_")[0]
                if lang and lang.lower() != "c":
                    return lang
        return None

    def locale_display_name(self, code: str) -> Optional[str]:
        return None