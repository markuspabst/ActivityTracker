"""Tests for the internationalization layer (i18n.py)."""

import os
from unittest.mock import patch, MagicMock

import pytest

import i18n


@pytest.fixture(autouse=True)
def _reset_translations():
    """Ensure translations global is reset between tests."""
    saved = (i18n._translations.copy(), i18n._lang)
    yield
    i18n._translations, i18n._lang = saved


def test_available_locales_includes_en_and_de():
    locales = i18n.available_locales()
    assert "en" in locales
    assert "de" in locales


def test_get_locales_dir_exists():
    d = i18n._get_locales_dir()
    assert d.exists()
    assert (d / "en.json").exists()


def test_set_locale_english_and_translate():
    i18n.set_locale("en")
    assert i18n.t("QUIT") == "Quit ActivityTracker"


def test_set_locale_german():
    i18n.set_locale("de")
    # German translation of QUIT (verify it differs from the key / English)
    val = i18n.t("QUIT")
    assert val != "QUIT"
    assert isinstance(val, str)


def test_set_locale_falls_back_to_english_for_unknown():
    i18n.set_locale("fr")  # no fr.json -> falls back to en
    assert i18n._lang == "en"
    assert i18n.t("QUIT") == "Quit ActivityTracker"


def test_t_with_format_kwargs():
    i18n.set_locale("en")
    assert i18n.t("MENU_ACTIVE", value="5h") == "Today's active: 5h"


def test_t_missing_key_returns_key():
    i18n.set_locale("en")
    assert i18n.t("NONEXISTENT_KEY") == "NONEXISTENT_KEY"


def test_t_format_failure_returns_raw():
    """If the translation requires kwargs but none are supplied, return raw text."""
    i18n.set_locale("en")
    raw = i18n.t("MENU_ACTIVE")  # needs {value}
    assert raw == "Today's active: {value}"


def test_t_handles_percentage_format():
    i18n.set_locale("en")
    out = i18n.t("TODAY_PROGRESS", active="1h", target="8h", percentage=12.5)
    assert "12%" in out


def test_get_system_locale_from_env(monkeypatch):
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.setenv("LC_ALL", "")
    monkeypatch.setenv("LANGUAGE", "")
    assert i18n._get_system_locale() == "de"


def test_get_system_locale_default_when_unset(monkeypatch):
    for var in ("LC_ALL", "LANGUAGE", "LANG"):
        monkeypatch.delenv(var, raising=False)
    # With no env vars, no stdlib locale, and a fallback platform -> 'en'
    import locale as _locale
    monkeypatch.setattr(_locale, "getdefaultlocale", lambda: (None, None))
    monkeypatch.setattr(_locale, "getlocale", lambda: (None, None))
    with patch.object(i18n, "get_platform") as mock_get:
        mock_get.return_value.get_system_locale.return_value = None
        assert i18n._get_system_locale() == "en"


def test_load_translations_handles_missing_file(tmp_path, monkeypatch):
    """Point locales dir at an empty temp dir; should fall back gracefully."""
    monkeypatch.setattr(i18n, "_get_locales_dir", lambda: tmp_path)
    i18n.load_translations("en")
    # No crash; translations empty, lang default
    assert i18n._translations == {}


def test_get_system_locale_via_platform(monkeypatch):
    """When env/stdlib give nothing, fall back to the platform API."""
    for var in ("LC_ALL", "LANGUAGE", "LANG"):
        monkeypatch.delenv(var, raising=False)
    import locale as _locale
    monkeypatch.setattr(_locale, "getdefaultlocale", lambda: (None, None))
    monkeypatch.setattr(_locale, "getlocale", lambda: (None, None))

    mock_plat = MagicMock()
    mock_plat.get_system_locale.return_value = "fr"
    with patch.object(i18n, "get_platform", return_value=mock_plat):
        assert i18n._get_system_locale() == "fr"
