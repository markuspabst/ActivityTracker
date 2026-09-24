import plistlib
import sys
from types import SimpleNamespace

from activitytracker.platform_layer import macos


def test_bundle_info_plist_is_read(tmp_path, monkeypatch):
    plist_path = tmp_path / "ActivityTracker.app" / "Contents" / "Info.plist"
    plist_path.parent.mkdir(parents=True)
    plist_path.write_bytes(plistlib.dumps({"CFBundleShortVersionString": "1.2.3"}))

    platform = macos.MacOSPlatform()
    monkeypatch.setattr(platform, "get_app_bundle_path", lambda: str(plist_path.parents[1]))

    assert platform._get_bundle_info_plist() == {"CFBundleShortVersionString": "1.2.3"}


def test_launch_agent_plist_is_written(tmp_path, monkeypatch):
    launch_agent_file = tmp_path / "LaunchAgents" / "activitytracker.plist"
    monkeypatch.setattr(macos, "LAUNCH_AGENT_DIR", str(launch_agent_file.parent))
    monkeypatch.setattr(macos, "LAUNCH_AGENT_FILE", str(launch_agent_file))
    monkeypatch.setattr(macos, "LOG_DIR", str(tmp_path / "Logs"))
    monkeypatch.setattr(macos.MacOSPlatform, "_get_app_executable_path", lambda self: "/Applications/ActivityTracker")

    macos.MacOSPlatform()._write_launch_agent_plist()

    with launch_agent_file.open("rb") as stream:
        saved = plistlib.load(stream)
    assert saved["ProgramArguments"] == ["/Applications/ActivityTracker"]


def test_get_idle_time_uses_ioreg_when_quartz_fails(monkeypatch):
    platform = macos.MacOSPlatform()
    monkeypatch.setattr(macos.MacOSPlatform, "_idle_cache", {"time": 0.0, "value": None})
    monkeypatch.setattr(macos.time, "time", lambda: 10.0)

    def fail_quartz(*_args):
        raise RuntimeError("Quartz unavailable")

    monkeypatch.setitem(sys.modules, "Quartz", SimpleNamespace(
        CGEventSourceSecondsSinceLastEventType=fail_quartz,
        kCGEventSourceStateHIDSystemState=1,
        kCGAnyInputEventType=2,
    ))
    monkeypatch.setattr(
        macos.subprocess,
        "check_output",
        lambda *_args, **_kwargs: b'"HIDIdleTime" = 2500000000',
    )

    assert platform.get_idle_time() == 2.5


def test_get_idle_time_returns_none_when_all_sources_fail(monkeypatch):
    platform = macos.MacOSPlatform()
    monkeypatch.setattr(macos.MacOSPlatform, "_idle_cache", {"time": 0.0, "value": None})
    monkeypatch.setattr(macos.time, "time", lambda: 10.0)

    def fail_quartz(*_args):
        raise RuntimeError("Quartz unavailable")

    monkeypatch.setitem(sys.modules, "Quartz", SimpleNamespace(
        CGEventSourceSecondsSinceLastEventType=fail_quartz,
        kCGEventSourceStateHIDSystemState=1,
        kCGAnyInputEventType=2,
    ))

    def fail_ioreg(*_args, **_kwargs):
        raise OSError("ioreg unavailable")

    monkeypatch.setattr(macos.subprocess, "check_output", fail_ioreg)

    assert platform.get_idle_time() is None
