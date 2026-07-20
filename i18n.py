import json
import locale
import os
import sys
from pathlib import Path

from platform_layer import get_platform

_translations = {}
_lang = None


def _get_locales_dir():
    base_dir = Path(__file__).resolve().parent
    local_path = base_dir / "locales"
    if local_path.exists():
        return local_path

    # py2app bundles non-code files into the app Resources folder.
    bundle_path = Path(sys.executable).resolve().parent.parent / "Resources" / "locales"
    if bundle_path.exists():
        return bundle_path

    return local_path


def _get_system_locale():
    # Try environment variables first (works on all platforms)
    for env_var in ("LC_ALL", "LANGUAGE", "LANG"):
        value = os.environ.get(env_var)
        if value:
            lang = value.split(".")[0].split("_")[0]
            if lang and lang.lower() != "c":
                return lang

    # Try stdlib locale module
    sys_loc = locale.getlocale()[0] or locale.getdefaultlocale()[0]
    if sys_loc:
        lang = sys_loc.split(".")[0].split("_")[0]
        if lang and lang.lower() != "c":
            return lang

    # Try platform-specific API
    plat = get_platform()
    platform_lang = plat.get_system_locale()
    if platform_lang:
        return platform_lang

    return "en"


def load_translations(lang):
    global _translations, _lang
    locales_dir = _get_locales_dir()
    if not lang:
        lang = _get_system_locale()

    lang = lang.split("-")[0]

    requested_file = locales_dir / f"{lang}.json"
    if requested_file.exists():
        candidate = requested_file
    else:
        candidate = locales_dir / "en.json"

    try:
        with open(candidate, "r", encoding="utf-8") as f:
            _translations = json.load(f)
            _lang = candidate.stem
    except Exception:
        _translations = {}
        _lang = "en"


def set_locale(lang=None):
    load_translations(lang)


def t(key, **kwargs):
    val = _translations.get(key)
    if val is None:
        val = key

    try:
        return val.format(**kwargs)
    except Exception:
        return val


def available_locales():
    locales_dir = _get_locales_dir()
    return [p.stem for p in locales_dir.glob("*.json")]
