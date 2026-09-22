#!/bin/bash
# Release script for ActivityTracker
# Usage: ./scripts/release.sh <major|minor|patch>

set -e

VERSION_PART=${1:-patch}

# Bump version
python3 scripts/bump_version.py --tag

# Build the app
briefcase build macOS

# Verify build exists
if [ ! -f "dist/ActivityTracker.app" ]; then
    echo "ERROR: Build failed - dist/ActivityTracker.app not found"
    exit 1
fi

echo ""
echo "Release preparation complete!"
echo ""
echo "To push changes and create GitHub release, run:"
echo "  git push --follow-tags"
echo ""
echo "Or manually:"
echo "  git push origin main"
echo "  git push origin v*.*.*"
echo ""
echo "GitHub Actions will automatically create the release with the built app."
