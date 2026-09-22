#!/bin/bash
# Release script for ActivityTracker
# Version is managed in pyproject.toml.

set -e

# Build the app (briefcase builds to build/activitytracker/macos/app/)
briefcase build macOS

# Verify build exists
if [ ! -d "build/activitytracker/macos/app/ActivityTracker.app" ]; then
    echo "ERROR: Build failed - build/activitytracker/macos/app/ActivityTracker.app not found"
    exit 1
fi

echo ""
echo "Release preparation complete!"
echo ""
echo "To push changes and create GitHub release, run:"
echo "  git push --follow-tags"
echo ""
echo "Note: The app is built to build/activitytracker/macos/app/ActivityTracker.app"
echo "GitHub Actions will automatically create the release with the built app."
