"""Tests for the version-bumping script (scripts/bump_version.py)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.bump_version as bump


@pytest.fixture
def version_files(tmp_path, monkeypatch):
    vf = tmp_path / "version.json"
    gf = tmp_path / "version_generated.py"
    monkeypatch.setattr(bump, "VERSION_FILE", vf)
    monkeypatch.setattr(bump, "VERSION_GENERATED", gf)
    return vf, gf


def test_read_version_default_when_missing(version_files):
    vf, _ = version_files
    if vf.exists():
        vf.unlink()
    v = bump.read_version()
    assert v == {"major": 1, "minor": 0, "patch": 0, "build": 0, "build_date": "dev"}


def test_read_version_existing(version_files):
    vf, _ = version_files
    vf.write_text(json.dumps({"major": 2, "minor": 3, "patch": 4, "build": 9, "build_date": "x"}))
    assert bump.read_version()["build"] == 9


def test_write_version_and_generated(version_files):
    vf, gf = version_files
    v = {"major": 1, "minor": 2, "patch": 3, "build": 7, "build_date": "2026-07-17"}
    bump.write_version(v)
    bump.write_version_generated(v)

    written = json.loads(vf.read_text())
    assert written["build"] == 7

    gen = gf.read_text()
    assert 'APP_VERSION = "1.2.3"' in gen
    assert 'APP_BUILD = "7"' in gen
    assert 'APP_FULL_VERSION = "1.2.3 (7)"' in gen
    assert 'APP_BUILD_DATE = "2026-07-17"' in gen


def test_main_increments_build(version_files):
    vf, gf = version_files
    vf.write_text(json.dumps({"major": 1, "minor": 0, "patch": 0, "build": 4, "build_date": "dev"}))

    # Execute the module's __main__ block. We strip the source's own
    # `VERSION_FILE = ...` / `VERSION_GENERATED = ...` assignments and instead
    # inject our temp paths into the exec globals, so the re-defined functions
    # (whose __globals__ become these globs) read/write the temp files.
    src = Path(bump.__file__).read_text()
    src = "\n".join(
        line for line in src.splitlines()
        if not line.startswith("VERSION_FILE =")
        and not line.startswith("VERSION_GENERATED =")
    )
    globs = dict(bump.__dict__)
    globs["__name__"] = "__main__"
    globs["VERSION_FILE"] = vf
    globs["VERSION_GENERATED"] = gf
    with patch.object(bump, "datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-07-17 00:00:00"
        exec(compile(src, bump.__file__, "exec"), globs)

    updated = json.loads(vf.read_text())
    assert updated["build"] == 5
    assert "APP_BUILD = \"5\"" in gf.read_text()
