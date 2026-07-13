# ActivityTracker Requirements

This document outlines the functional and non-functional requirements for the ActivityTracker application.

## Functional Requirements

### Time Tracking

- The application shall track the user's active and idle time on their computer.
- The application shall distinguish between active and idle time based on user input (or lack thereof).
- The application shall not track any time when the user's screen is locked.

### Session Management

- A new tracking session shall begin when the application is launched.
- The tracking session shall automatically reset at midnight.
- The application shall be able to recover unsaved time from a previous session if it did not shut down correctly.

### Data Persistence

- All tracked time data shall be saved to a local CSV file.
- Data shall be saved automatically at user-configurable intervals.
- Data shall be saved automatically when the application is quit.

### Configuration

- The user shall be able to set a daily and weekly target for their active time.
- The user shall be able to configure the duration of inactivity that is considered "idle time".
- The user shall be able to configure the interval at which data is saved.
- The user shall be able to specify the directory where the data file is stored.

### User Interface

- The application shall provide a menu bar icon.
- The menu bar icon shall indicate the current status (e.g., active, idle, target met).
- The menu shall display statistics for the current day.
- The menu shall provide options to:
    - Force an immediate save of the tracked time.
    - Open the folder containing the data file.
    - Quit the application.

### Autostart

- The user shall be able to configure the application to launch automatically on system startup.

## Non-Functional Requirements

### Platform Support

- The application shall be compatible with macOS, Windows, and Linux.

### Performance

- The application shall have a minimal impact on system performance.

### Reliability

- The application must be stable and not prone to crashing or data loss.
