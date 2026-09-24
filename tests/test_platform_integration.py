from unittest.mock import MagicMock

from activitytracker import activity_tracker_menu, platform_layer
from activitytracker.platform_layer.macos import MacOSPlatform


def test_macos_platform_is_wired_to_status_menu(monkeypatch):
    monkeypatch.setattr(platform_layer, "_platform_instance", None)
    monkeypatch.setattr(platform_layer.sys, "platform", "darwin")
    macos_platform = platform_layer.get_platform()
    assert isinstance(macos_platform, MacOSPlatform)

    icon_image = object()
    icon_instance = object()
    menu_instance = object()
    icon_factory = MagicMock(return_value=icon_instance)
    menu_factory = MagicMock(return_value=menu_instance)
    monkeypatch.setattr(activity_tracker_menu, "get_platform", lambda: macos_platform)
    monkeypatch.setattr(activity_tracker_menu, "Icon", icon_factory)
    monkeypatch.setattr(activity_tracker_menu, "Menu", menu_factory)
    monkeypatch.setattr(activity_tracker_menu, "create_icon", lambda *_args: icon_image)
    monkeypatch.setattr(
        activity_tracker_menu,
        "run_on_main_thread",
        lambda callback, *args: callback(*args),
    )

    menu = activity_tracker_menu.AppMenu(MagicMock())

    assert menu.platform is macos_platform
    icon_factory.assert_called_once_with("ActivityTracker", icon_image, "ActivityTracker", menu_instance)
