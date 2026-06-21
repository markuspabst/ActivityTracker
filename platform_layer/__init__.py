"""
Platform abstraction layer for ActivityTracker.

Define an abstract base class that all platform implementations must satisfy.
New platforms (Windows, Linux, etc.) simply implement this interface.
"""

from __future__ import annotations

import abc
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional, Tuple


# ------------------------------------------------------------
# Abstract Base
# ------------------------------------------------------------

class PlatformABC(abc.ABC):
    """Interface that every platform backend must implement."""

    # ── Idle detection ──────────────────────────────────────

    @abc.abstractmethod
    def get_idle_time(self) -> float:
        """Seconds since last HID input event."""
        ...

    # ── App bundle / version info ───────────────────────────

    def get_app_bundle_path(self) -> Optional[str]:
        """Path to the .app bundle, or None if not running from a bundle."""
        return None

    @abc.abstractmethod
    def get_bundle_version(self, fallback: str = "dev") -> str:
        """Human-readable version string from the bundle or fallback."""
        ...

    @abc.abstractmethod
    def get_bundle_build_date(self, fallback: str = "dev") -> str:
        """Build date string from the bundle or fallback."""
        ...

    # ── Dialogs ─────────────────────────────────────────────

    def supports_native_dialogs(self) -> bool:
        """Whether the platform can show native input dialogs."""
        return False

    def bring_app_to_front(self) -> None:
        """Bring the application window to front (for dialog input)."""

    def ask_slider_dialog(
        self, title: str, current: float,
        min_value: float = 0, max_value: float = 100,
    ) -> Optional[float]:
        """Modal dialog with a numeric input.  Return None on cancel."""
        return None

    def choose_folder_dialog(self, prompt: str = "") -> Optional[str]:
        """Native folder picker.  Return None on cancel."""
        return None

    # ── Autostart ───────────────────────────────────────────

    @abc.abstractmethod
    def autostart_installed(self) -> bool: ...

    @abc.abstractmethod
    def autostart_loaded(self) -> bool: ...

    @abc.abstractmethod
    def install_autostart(self) -> None: ...

    @abc.abstractmethod
    def uninstall_autostart(self) -> None: ...

    # ── File manager ────────────────────────────────────────

    @abc.abstractmethod
    def open_file_manager(self, path: str) -> None: ...

    @abc.abstractmethod
    def reveal_file_in_manager(self, path: str) -> None: ...

    # ── Autostart config path (for "Open autostart file") ───

    def get_autostart_config_path(self) -> Optional[Tuple[str, str]]:
        """Return (config_dir, config_file_path) or None."""
        return None

    # ── Dashboard scripting ─────────────────────────────────

    @abc.abstractmethod
    def find_dashboard_script(self) -> Path:
        """Locate generate_dashboard.py in the source tree or bundle."""
        ...

    def get_dashboard_python_cmd(self) -> Tuple[str, Optional[dict]]:
        """Return (executable, env_override) for running the dashboard script."""
        return sys.executable, None

    # ── Locale helpers ──────────────────────────────────────

    def get_system_locale(self) -> Optional[str]:
        """Return the user's preferred language code, or None."""
        return None

    def locale_display_name(self, code: str) -> Optional[str]:
        """Localised display name for a locale code, or None."""
        return None


# ------------------------------------------------------------
# Platform detection + factory
# ------------------------------------------------------------

_platform_instance: Optional[PlatformABC] = None


def detect_platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def get_platform() -> PlatformABC:
    global _platform_instance
    if _platform_instance is not None:
        return _platform_instance

    detected = detect_platform()

    if detected == "macos":
        from platform_layer.macos import MacOSPlatform
        _platform_instance = MacOSPlatform()
    elif detected == "windows":
        from platform_layer.windows import WindowsPlatform
        _platform_instance = WindowsPlatform()
    elif detected == "linux":
        from platform_layer.linux import LinuxPlatform
        _platform_instance = LinuxPlatform()
    else:
        _platform_instance = FallbackPlatform()

    return _platform_instance


def set_platform(platform: PlatformABC) -> None:
    """Override the active platform (useful for testing)."""
    global _platform_instance
    _platform_instance = platform


# ------------------------------------------------------------
# Fallback (generic) implementation
# ------------------------------------------------------------

class FallbackPlatform(PlatformABC):
    """Generic implementation that works anywhere but has no native niceties."""

    _idle_cache: dict = {"time": 0.0, "value": 0.0}
    IDLE_CACHE_TTL: float = 1.0

    def get_idle_time(self) -> float:
        now = time.time()
        if now - self._idle_cache["time"] < self.IDLE_CACHE_TTL:
            return self._idle_cache["value"]
        # No reliable cross-platform idle detection without dependencies
        self._idle_cache.update(time=now, value=0.0)
        return 0.0

    def get_bundle_version(self, fallback: str = "dev") -> str:
        return fallback

    def get_bundle_build_date(self, fallback: str = "dev") -> str:
        return fallback

    def autostart_installed(self) -> bool:
        return False

    def autostart_loaded(self) -> bool:
        return False

    def install_autostart(self) -> None:
        raise NotImplementedError("Autostart not implemented on this platform")

    def uninstall_autostart(self) -> None:
        raise NotImplementedError("Autostart not implemented on this platform")

    def open_file_manager(self, path: str) -> None:
        print(f"Open file manager: {path}")

    def reveal_file_in_manager(self, path: str) -> None:
        self.open_file_manager(os.path.dirname(path))

    def get_autostart_config_path(self) -> Optional[Tuple[str, str]]:
        return None

    def find_dashboard_script(self) -> Path:
        return Path(__file__).resolve().parent.parent / "scripts" / "generate_dashboard.py"