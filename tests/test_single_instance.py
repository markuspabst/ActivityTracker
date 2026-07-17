"""Tests for the single-instance lock (single_instance.py)."""

import pytest

import single_instance
from single_instance import SingleInstanceLock


@pytest.fixture
def isolate_runtime(tmp_path, monkeypatch):
    # Redirect the runtime dir so we don't collide with a real running instance
    # (the production lock lives in the user's runtime dir and may be held).
    monkeypatch.setattr(single_instance.platformdirs, "user_runtime_dir",
                        lambda *a, **k: str(tmp_path))
    yield


def test_acquire_and_release(isolate_runtime):
    lock = SingleInstanceLock()
    try:
        assert lock.acquire() is True
    finally:
        lock.release()


def test_second_instance_is_blocked(isolate_runtime):
    lock1 = SingleInstanceLock()
    lock2 = SingleInstanceLock()
    try:
        assert lock1.acquire() is True
        # A second lock on the same lock file must fail (non-blocking flock)
        assert lock2.acquire() is False
    finally:
        lock1.release()
        lock2.release()


def test_release_is_safe_when_not_acquired(isolate_runtime):
    lock = SingleInstanceLock()
    # release() without acquire must not raise
    lock.release()
