#!/bin/bash
# Build, tag, and publish a release. Version is managed in pyproject.toml.

set -euo pipefail

VERSION=$(sed -n 's/^version = "\([^"]*\)"/\1/p' pyproject.toml | head -n 1)
if [ -z "$VERSION" ]; then
    echo "ERROR: Could not read version from pyproject.toml"
    exit 1
fi

TAG="v${VERSION}"
BRIEFCASE="${BRIEFCASE:-.venv/bin/briefcase}"

if [ ! -x "$BRIEFCASE" ]; then
    BRIEFCASE="briefcase"
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "ERROR: Commit all changes before creating a release."
    exit 1
fi

if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "ERROR: Tag $TAG already exists."
    exit 1
fi

# Build the app (briefcase builds to build/activitytracker/macos/app/)
"$BRIEFCASE" build macOS

# Verify build exists
if [ ! -d "build/activitytracker/macos/app/ActivityTracker.app" ]; then
    echo "ERROR: Build failed - build/activitytracker/macos/app/ActivityTracker.app not found"
    exit 1
fi

echo ""
echo "Release preparation complete!"
echo ""
echo "Creating GitHub release with tag $TAG..."
git tag -a "$TAG" -m "Release $TAG"
git push origin "$TAG"
echo ""
echo "Note: The app is built to build/activitytracker/macos/app/ActivityTracker.app"
echo "GitHub Actions will now create the release."
