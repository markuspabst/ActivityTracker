
import sys
import os
import atexit
import platformdirs

# fcntl is Unix-specific, which is fine for our macOS target.
try:
    import fcntl
except ImportError:
    # This will cause the lock to be a no-op on non-Unix platforms,
    # which is acceptable for development on other systems.
    fcntl = None

APP_NAME = "ActivityTracker"
LOCK_FILE_NAME = "activity_tracker.lock"

class SingleInstanceLock:
    """
    Enforces that only one instance of the application can be running at a time.
    """
    def __init__(self):
        if not fcntl:
            return

        runtime_dir = platformdirs.user_runtime_dir(APP_NAME, ensure_exists=True)
        self.lockfile_path = os.path.join(runtime_dir, LOCK_FILE_NAME)
        self.fp = None

    def acquire(self) -> bool:
        """
        Acquires the lock. Returns True if successful, False otherwise.
        """
        if not fcntl:
            return True # Always succeed if fcntl is not available

        try:
            self.fp = open(self.lockfile_path, 'w')
            # Try to acquire an exclusive, non-blocking lock.
            fcntl.flock(self.fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # If we're here, we got the lock. Write our PID and register cleanup.
            self.fp.write(str(os.getpid()))
            self.fp.flush()
            atexit.register(self.release)
            return True
        except (IOError, BlockingIOError):
            # Another instance is holding the lock.
            if self.fp:
                self.fp.close()
            return False

    def release(self):
        """
        Releases the lock and cleans up the lock file.
        """
        if not fcntl or not self.fp:
            return

        try:
            fcntl.flock(self.fp.fileno(), fcntl.LOCK_UN)
            self.fp.close()
            os.remove(self.lockfile_path)
        except Exception as e:
            # Log errors on release, but don't crash the exit sequence.
            print(f"Error releasing single instance lock: {e}", file=sys.stderr)

