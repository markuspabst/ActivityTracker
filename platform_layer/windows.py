"""
Windows platform implementation for ActivityTracker.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

from platform_layer import PlatformABC


APP_NAME = "ActivityTracker"
AUTOSTART_REG_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Run"
)


class WindowsPlatform(PlatformABC):

    _idle_cache: dict = {"time": 0.0, "value": 0.0}
    IDLE_CACHE_TTL: float = 1.0

    # ── Idle detection ──────────────────────────────────────
    # Uses GetLastInputInfo from user32.dll

    def get_idle_time(self) -> float:
        now = time.time()
        if now - self._idle_cache["time"] < self.IDLE_CACHE_TTL:
            return self._idle_cache["value"]

        try:
            from ctypes import Structure, byref, c_uint, sizeof, windll

            class LASTINPUTINFO(Structure):
                _fields_ = [("cbSize", c_uint), ("dwTime", c_uint)]

            info = LASTINPUTINFO()
            info.cbSize = sizeof(info)
            windll.user32.GetLastInputInfo(byref(info))
            value = (windll.kernel32.GetTickCount() - info.dwTime) / 1000.0
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

    def ask_slider_dialog(
        self, title: str, current: float,
        min_value: float = 0, max_value: float = 100,
    ) -> Optional[float]:
        return None

    def choose_folder_dialog(self, prompt: str = "") -> Optional[str]:
        return None

    # ── Autostart (Registry Run key) ────────────────────────

    @staticmethod
    def _get_app_exe_path() -> Optional[str]:
        """Return the path to the executable for autostart."""
        if getattr(sys, "frozen", False):
            return sys.executable
        # When running as a script, use pythonw.exe to avoid a console window
        pythonw = Path(sys.executable).parent / "pythonw.exe"
        return str(pythonw) if pythonw.exists() else sys.executable

    def autostart_installed(self) -> bool:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_READ
            )
            try:
                value, _ = winreg.QueryValueEx(key, APP_NAME)
                return bool(value)
            finally:
                winreg.CloseKey(key)
        except (OSError, ImportError):
            return False

    def autostart_loaded(self) -> bool:
        return self.autostart_installed()

    def install_autostart(self) -> None:
        exe_path = self._get_app_exe_path()
        if not exe_path:
            raise RuntimeError("Cannot determine executable path for autostart")
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
            winreg.CloseKey(key)
        except (OSError, ImportError) as e:
            raise RuntimeError(f"Failed to install autostart: {e}")

    def uninstall_autostart(self) -> None:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_SET_VALUE
            )
            winreg.DeleteValue(key, APP_NAME)
            winreg.CloseKey(key)
        except (OSError, ImportError):
            pass

    # ── File manager ────────────────────────────────────────

    def open_file_manager(self, path: str) -> None:
        subprocess.run(["explorer", path])

    def reveal_file_in_manager(self, path: str) -> None:
        subprocess.run(["explorer", "/select,", path])

    # ── Autostart config path ────────────────────────────

    def get_autostart_config_path(self) -> Optional[Tuple[str, str]]:
        return (r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run", "")

    # ── Dashboard scripting ─────────────────────────────────

    def find_dashboard_script(self) -> Path:
        return Path(__file__).resolve().parent.parent / "scripts" / "generate_dashboard.py"

    # ── Locale helpers ──────────────────────────────────────

    def get_system_locale(self) -> Optional[str]:
        try:
            import ctypes
            windll = ctypes.windll.kernel32
            buf = ctypes.create_unicode_buffer(9)
            windll.GetUserDefaultLocaleName(buf, 9)
            return buf.value.split("-")[0].lower()
        except Exception:
            pass
        return None

    def locale_display_name(self, code: str) -> Optional[str]:
        try:
            import ctypes
            windll = ctypes.windll.kernel32
            buf = ctypes.create_unicode_buffer(256)
            # LOCALE_SLOCALIZEDDISPLAYNAME = 0x6C
            windll.GetLocaleInfoEx(code, 0x6C, buf, 256)
            name = buf.value
            if name:
                return name
        except Exception:
            pass
        return None