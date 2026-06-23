"""
macOS platform implementation for ActivityTracker.
"""

from __future__ import annotations

import functools
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

from platform_layer import PlatformABC


# ------------------------------------------------------------
# Helper for running code on the main thread
# ------------------------------------------------------------
try:
    from Foundation import NSObject
    import objc

    class _MainThreadRunner(NSObject):
        def initWithCallable_args_kwargs_(self, callable_fn, args, kwargs):
            self = objc.super(_MainThreadRunner, self).init()
            if self is None:
                return None
            self.callable_fn = callable_fn
            self.args = args
            self.kwargs = kwargs
            self.result = None
            self.exception = None
            return self

        def run(self):
            try:
                self.result = self.callable_fn(*self.args, **self.kwargs)
            except Exception as e:
                self.exception = e

    def _run_on_main(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            runner = _MainThreadRunner.alloc().initWithCallable_args_kwargs_(
                func, args, kwargs
            )
            runner.performSelectorOnMainThread_withObject_waitUntilDone_("run", None, True)
            if runner.exception:
                raise runner.exception
            return runner.result
        return wrapper

    _CAN_RUN_ON_MAIN = True

except Exception:
    _MainThreadRunner = None  # noqa
    def _run_on_main(func):
        return func # Passthrough if pyobjc fails
    _CAN_RUN_ON_MAIN = False


from platform_layer import PlatformABC


APP_NAME = "ActivityTracker"

LAUNCH_AGENT_LABEL = "com.markus.activitytracker"
LAUNCH_AGENT_DIR = os.path.expanduser("~/Library/LaunchAgents")
LAUNCH_AGENT_FILE = os.path.join(LAUNCH_AGENT_DIR, f"{LAUNCH_AGENT_LABEL}.plist")
LOG_DIR = os.path.expanduser("~/Library/Logs/ActivityTracker")
LAUNCH_AGENT_OUT = os.path.join(LOG_DIR, "activitytracker.out.log")
LAUNCH_AGENT_ERR = os.path.join(LOG_DIR, "activitytracker.err.log")


# ------------------------------------------------------------
# Helper ObjC class for the slider dialog
# ------------------------------------------------------------
try:
    from Foundation import NSObject
    import objc

    class _SliderHandler(NSObject):
        """Receives NSSlider action messages and updates the value label."""

        def initWithLabel_(self, label):
            self = objc.super(_SliderHandler, self).init()
            if self is None:
                return None
            self._label = label
            return self

        @objc.typedSelector(b"v@:@")
        def sliderChanged_(self, sender):
            self._label.setStringValue_(f"{sender.doubleValue():.1f}")

    _HAS_SLIDER_HANDLER = True
except Exception:
    _SliderHandler = None  # noqa
    _HAS_SLIDER_HANDLER = False


class MacOSPlatform(PlatformABC):

    _idle_cache: dict = {"time": 0.0, "value": 0.0}
    IDLE_CACHE_TTL: float = 1.0

    # ── Idle detection ──────────────────────────────────────

    def get_idle_time(self) -> float:
        now = time.time()
        if now - self._idle_cache["time"] < self.IDLE_CACHE_TTL:
            return self._idle_cache["value"]

        try:
            import Quartz
            value = Quartz.CGEventSourceSecondsSinceLastEventType(
                Quartz.kCGEventSourceStateHIDSystemState,
                Quartz.kCGAnyInputEventType,
            )
        except Exception:
            try:
                output = subprocess.check_output(
                    ["ioreg", "-c", "IOHIDSystem"], stderr=subprocess.DEVNULL
                ).decode()
                value = 0.0
                for line in output.split("\n"):
                    if "HIDIdleTime" in line:
                        value = int(line.split("=")[-1].strip()) / 1_000_000_000
                        break
            except Exception:
                value = 0.0

        self._idle_cache.update(time=now, value=value)
        return value

    # ── App bundle / version info ───────────────────────────

    def get_app_bundle_path(self) -> Optional[str]:
        executable = Path(sys.executable).resolve()
        for parent in [executable] + list(executable.parents):
            if parent.suffix == ".app":
                return str(parent)
        return None

    def _get_bundle_info_plist(self) -> Optional[dict]:
        try:
            app_path = self.get_app_bundle_path()
            if not app_path:
                return None
            plist_path = Path(app_path) / "Contents" / "Info.plist"
            if not plist_path.exists():
                return None
            with open(plist_path, "rb") as f:
                return plistlib.load(f)
        except Exception:
            return None

    @functools.lru_cache(maxsize=1)
    def get_bundle_version(self, fallback: str = "dev") -> str:
        plist = self._get_bundle_info_plist()
        if plist:
            version = plist.get("CFBundleShortVersionString", "unknown")
            build = plist.get("CFBundleVersion", "")
            return f"{version} ({build})" if build else version
        return fallback

    @functools.lru_cache(maxsize=1)
    def get_bundle_build_date(self, fallback: str = "dev") -> str:
        plist = self._get_bundle_info_plist()
        if plist:
            return plist.get("ActivityTrackerBuildDate", fallback)
        return fallback

    # ── Dialogs ─────────────────────────────────────────────

    def supports_native_dialogs(self) -> bool:
        return True

    def bring_app_to_front(self) -> None:
        try:
            from AppKit import NSApplication
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception:
            pass

    def ask_slider_dialog(
        self, title: str, current: float,
        min_value: float = 0, max_value: float = 100,
    ) -> Optional[float]:
        """Native dialog with a slider.

        Note: pystray menu callbacks run on a background thread, so we use
        osascript for the dialog to avoid beachball cursor from AppKit calls
        on non-main threads.
        """
        if _CAN_RUN_ON_MAIN:
            return self._ask_slider_native(title, current, min_value, max_value)
        return self._ask_slider_osascript(title, current, min_value, max_value)

    @_run_on_main
    def _ask_slider_native(self, title, current, min_value, max_value):
        """AppKit-based slider dialog (main thread only)."""
        if not _HAS_SLIDER_HANDLER:
            return None
        try:
            from AppKit import (
                NSAlert,
                NSApplication,
                NSSlider,
                NSTextField,
                NSView,
                NSMakeRect,
                NSFont,
                NSTextAlignmentCenter,
            )

            alert = NSAlert.alloc().init()
            alert.setMessageText_(title)
            alert.addButtonWithTitle_("OK")
            alert.addButtonWithTitle_("Cancel")

            # Bring app to front
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

            # Custom view: slider + live value label
            view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 55))

            slider = NSSlider.alloc().initWithFrame_(NSMakeRect(20, 5, 260, 30))
            slider.setMinValue_(min_value)
            slider.setMaxValue_(max_value)
            slider.setDoubleValue_(current)
            slider.setContinuous_(True)

            label = NSTextField.alloc().initWithFrame_(NSMakeRect(130, 28, 60, 22))
            label.setEditable_(False)
            label.setBezeled_(False)
            label.setDrawsBackground_(False)
            label.setStringValue_(f"{current:.1f}")
            label.setFont_(NSFont.systemFontOfSize_(14))
            label.setAlignment_(NSTextAlignmentCenter)

            handler = _SliderHandler.alloc().initWithLabel_(label)
            slider.setTarget_(handler)
            slider.setAction_("sliderChanged:")

            view.addSubview_(slider)
            view.addSubview_(label)
            alert.setAccessoryView_(view)

            subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to activate'],
                capture_output=True, check=False,
            )

            response = alert.runModal()
            if response == 1000:  # NSAlertFirstButtonReturn
                return max(min(slider.doubleValue(), max_value), min_value)
            return None
        except Exception as e:
            print(f"Native slider dialog failed: {e}")
            return None

    def _ask_slider_osascript(self, title, current, min_value, max_value):
        """osascript-based text input dialog (thread-safe)."""
        proc = subprocess.run(
            [
                "osascript", "-e",
                f'tell application "System Events" to set response to '
                f'display dialog "{title}" default answer "{current:.1f}" '
                f'buttons {{"Cancel", "OK"}} default button "OK"',
            ],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                # Output format: "button returned:OK, text returned:8.0"
                text = proc.stdout.strip()
                for part in text.split(","):
                    part = part.strip()
                    if part.startswith("text returned:"):
                        value = float(part.split(":", 1)[1])
                        return max(min(value, max_value), min_value)
            except ValueError:
                pass
        return None

    def choose_folder_dialog(self, prompt: str = "") -> Optional[str]:
        if _CAN_RUN_ON_MAIN:
            return self._choose_folder_native(prompt)
        return self._choose_folder_osascript(prompt)

    @_run_on_main
    def _choose_folder_native(self, prompt: str = "") -> Optional[str]:
        """AppKit-based folder chooser (main thread only)."""
        try:
            from AppKit import NSOpenPanel, NSApplication

            # Activate to bring the panel to the front
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

            panel = NSOpenPanel.openPanel()
            panel.setCanChooseFiles_(False)
            panel.setCanChooseDirectories_(True)
            panel.setCanCreateDirectories_(True)
            panel.setAllowsMultipleSelection_(False)
            if prompt:
                panel.setMessage_(prompt)

            if panel.runModal() == 1:
                return str(panel.URLs()[0].path()) if panel.URLs() else None
            return None
        except Exception as e:
            print(f"Native folder chooser failed: {e}")
            return None

    def _choose_folder_osascript(self, prompt: str = "") -> Optional[str]:
        # Use osascript to activate instead of AppKit to avoid
        # beachball cursor when called from a non-main thread.
        try:
            subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to activate'],
                capture_output=True, check=False,
            )
        except Exception:
            pass
        try:
            script = 'set f to choose folder'
            if prompt:
                script += f' with prompt "{prompt}"'
            script += '\nreturn POSIX path of f'
            r = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, check=False,
            )
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception as e:
            print(f"Error opening folder choice dialog: {e}")
            return None

    # ── Autostart (launchd) ─────────────────────────────────

    @staticmethod
    def _launchctl_domain() -> str:
        return f"gui/{os.getuid()}"

    def _get_app_executable_path(self) -> Optional[str]:
        app_path = self.get_app_bundle_path()
        if not app_path:
            return None
        exec_dir = Path(app_path) / "Contents" / "MacOS"
        if not exec_dir.exists():
            return None
        executables = [
            str(f) for f in exec_dir.iterdir()
            if f.is_file() and os.access(f, os.X_OK)
        ]
        return executables[0] if executables else None

    def _write_launch_agent_plist(self) -> None:
        app_executable = self._get_app_executable_path()
        if not app_executable:
            raise RuntimeError(
                "Autostart requires packaged ActivityTracker.app. Build with py2app first."
            )
        os.makedirs(LAUNCH_AGENT_DIR, exist_ok=True)
        os.makedirs(LOG_DIR, exist_ok=True)

        plist = {
            "Label": LAUNCH_AGENT_LABEL,
            "ProgramArguments": [app_executable],
            "RunAtLoad": True,
            "KeepAlive": False,
            "LimitLoadToSessionType": "Aqua",
            "StandardOutPath": LAUNCH_AGENT_OUT,
            "StandardErrorPath": LAUNCH_AGENT_ERR,
            "WorkingDirectory": str(Path(app_executable).parent),
        }
        with open(LAUNCH_AGENT_FILE, "wb") as f:
            plistlib.dump(plist, f)

    def autostart_installed(self) -> bool:
        return os.path.isfile(LAUNCH_AGENT_FILE)

    def autostart_loaded(self) -> bool:
        result = subprocess.run(
            ["launchctl", "print", f"{self._launchctl_domain()}/{LAUNCH_AGENT_LABEL}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0

    def install_autostart(self) -> None:
        self._write_launch_agent_plist()
        domain = self._launchctl_domain()
        subprocess.run(
            ["launchctl", "bootout", domain, LAUNCH_AGENT_FILE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["launchctl", "bootstrap", domain, LAUNCH_AGENT_FILE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["launchctl", "enable", f"{domain}/{LAUNCH_AGENT_LABEL}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def uninstall_autostart(self) -> None:
        subprocess.run(
            ["launchctl", "bootout", self._launchctl_domain(), LAUNCH_AGENT_FILE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if os.path.isfile(LAUNCH_AGENT_FILE):
            os.remove(LAUNCH_AGENT_FILE)

    # ── File manager ────────────────────────────────────────

    def open_file_manager(self, path: str) -> None:
        subprocess.run(["open", path])

    def reveal_file_in_manager(self, path: str) -> None:
        subprocess.run(["open", "-R", path])

    # ── Autostart config path ────────────────────────────

    def get_autostart_config_path(self) -> Optional[Tuple[str, str]]:
        return (LAUNCH_AGENT_DIR, LAUNCH_AGENT_FILE)

    # ── Dashboard scripting ─────────────────────────────────

    def find_dashboard_script(self) -> Path:
        local = Path(__file__).resolve().parent.parent / "scripts" / "generate_dashboard.py"
        if local.exists():
            return local
        app_path = self.get_app_bundle_path()
        if app_path:
            bundle = Path(app_path) / "Contents" / "Resources" / "scripts" / "generate_dashboard.py"
            if bundle.exists():
                return bundle
        return local

    def get_dashboard_python_cmd(self) -> Tuple[str, Optional[dict]]:
        app_path = self.get_app_bundle_path()
        if app_path:
            bundled_python = Path(app_path) / "Contents" / "MacOS" / "python"
            resources = Path(app_path) / "Contents" / "Resources"
            lib_dir = resources / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
            if bundled_python.exists() and lib_dir.exists():
                env = os.environ.copy()
                env["PYTHONHOME"] = str(resources)
                env["PYTHONPATH"] = os.pathsep.join([
                    str(lib_dir),
                    str(lib_dir / "lib-dynload"),
                ])
                return str(bundled_python), env
        return sys.executable, None

    # ── Locale helpers ──────────────────────────────────────

    def get_system_locale(self) -> Optional[str]:
        try:
            from Foundation import NSUserDefaults
            langs = NSUserDefaults.standardUserDefaults().objectForKey_("AppleLanguages")
            if langs and len(langs) > 0:
                lang = str(langs[0]).split("-")[0]
                if lang and lang.lower() != "c":
                    return lang
        except Exception:
            pass
        return None

    def locale_display_name(self, code: str) -> Optional[str]:
        try:
            from Foundation import NSLocale, NSLocaleIdentifier
            loc = NSLocale.alloc().initWithLocaleIdentifier_(code)
            name = loc.displayNameForKey_value_(NSLocaleIdentifier, code)
            if name:
                return name[:1].upper() + name[1:]
        except Exception:
            pass
        return None