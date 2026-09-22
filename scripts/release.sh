#!/bin/bash
# Bump, build, tag, and publish a release. Version is managed in pyproject.toml.

set -euo pipefail

RELEASE_TYPE="${1:-patch}"
case "$RELEASE_TYPE" in
    major|minor|patch) ;;
    *) echo "ERROR: Release type must be major, minor, or patch."; exit 1 ;;
esac

PYTHON="${PYTHON:-.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "ERROR: Commit all changes before creating a release."
    exit 1
fi

VERSION=$(sed -n 's/^version = "\([^"]*\)"/\1/p' pyproject.toml | head -n 1)
if [ -z "$VERSION" ]; then
    echo "ERROR: Could not read version from pyproject.toml"
    exit 1
fi

NEW_VERSION=$("$PYTHON" - "$VERSION" "$RELEASE_TYPE" <<'PY'
import sys

version = sys.argv[1].split(".")
release_type = sys.argv[2]
if len(version) != 3 or not all(part.isdigit() for part in version):
    raise SystemExit(f"Invalid semantic version: {sys.argv[1]}")

major, minor, patch = map(int, version)
if release_type == "major":
    major, minor, patch = major + 1, 0, 0
elif release_type == "minor":
    minor, patch = minor + 1, 0
else:
    patch += 1
print(f"{major}.{minor}.{patch}")
PY
)

"$PYTHON" - "$NEW_VERSION" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path("pyproject.toml")
content = path.read_text()
updated = re.sub(
    r'^(version\s*=\s*)"[^"]*"$',
    rf'\g<1>"{sys.argv[1]}"',
    content,
    count=1,
    flags=re.MULTILINE,
)
if updated == content:
    raise SystemExit("Could not update version in pyproject.toml")
path.write_text(updated)
PY

VERSION="$NEW_VERSION"
TAG="v${VERSION}"
BRIEFCASE="${BRIEFCASE:-.venv/bin/briefcase}"

if [ ! -x "$BRIEFCASE" ]; then
    BRIEFCASE="briefcase"
fi

if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "ERROR: Tag $TAG already exists."
    exit 1
fi

git add pyproject.toml
git commit -m "Bump version to $VERSION"

# Build the app (briefcase builds to build/activitytracker/macos/app/)
"$BRIEFCASE" build macOS --no-input

# Package the distributable macOS installer.
"$BRIEFCASE" package macOS --no-input --adhoc-sign --packaging-format dmg

# Verify build exists
if [ ! -d "build/activitytracker/macos/app/ActivityTracker.app" ]; then
    echo "ERROR: Build failed - build/activitytracker/macos/app/ActivityTracker.app not found"
    exit 1
fi

if ! compgen -G "dist/ActivityTracker-*.dmg" > /dev/null; then
    echo "ERROR: DMG package was not created in dist/"
    exit 1
fi

echo ""
echo "Release preparation complete!"
echo ""
echo "Creating GitHub release with tag $TAG..."
git tag -a "$TAG" -m "Release $TAG"
git push origin "$TAG"
echo ""
echo "Note: The DMG package is in dist/"
echo "GitHub Actions will now create the release."
