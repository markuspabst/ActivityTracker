from setuptools import setup
from pathlib import Path
import json

APP = ["activity_tracker_menu.py"]

VERSION_FILE = Path("version.json")


def read_version():
    if not VERSION_FILE.exists():
        return "1.0.0", "0", "dev"

    with VERSION_FILE.open("r") as f:
        data = json.load(f)

    short_version = f"{data['major']}.{data['minor']}.{data['patch']}"
    build_version = str(data.get("build", 0))
    build_date = data.get("build_date", "dev")

    return short_version, build_version, build_date


APP_VERSION, APP_BUILD, APP_BUILD_DATE = read_version()


OPTIONS = {
    "argv_emulation": True,
    "plist": {
        "CFBundleName": "ActivityTracker",
        "CFBundleDisplayName": "ActivityTracker",
        "CFBundleIdentifier": "com.markus.activitytracker",

        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_BUILD,
        "ActivityTrackerBuildDate": APP_BUILD_DATE,

        "LSUIElement": True
    },
    "packages": ["rumps"],
    "includes": [
        "version_generated",
        "appdirs",
        "pydantic",
        "tenacity",
        "dateutil",
        "pandas"
    ]
}


DATA_FILES = [
    ("scripts", ["scripts/generate_dashboard.py"]),
    ("locales", [str(p) for p in sorted(Path("locales").glob("*.json"))])
]


setup(
    name="ActivityTracker",
    app=APP,
    options={"py2app": OPTIONS},
    data_files=DATA_FILES,
    setup_requires=["py2app"],
)