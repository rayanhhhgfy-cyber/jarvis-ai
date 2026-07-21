# ====================================================================
# JARVIS OMEGA — Scheduler Tests
# ====================================================================
"""
Smoke tests for the APScheduler-backed task scheduler.

Verifies interval and cron scheduling, listing, and cancellation, plus the
existing cron-expression parser (5-field POSIX-style).
"""

from __future__ import annotations

import pytest

from backend.scheduler import TaskScheduler


@pytest.fixture
def scheduler() -> TaskScheduler:
    s = TaskScheduler()
    # Don't call .start() — APScheduler BackgroundScheduler can be inspected
    # without running. Each test creates and tears down its own jobs.
    return s


def _noop():
    """Trivial callable for scheduling."""


def test_schedule_interval_adds_job(scheduler: TaskScheduler):
    jid = scheduler.schedule_interval(
        job_id="test-interval",
        func=_noop,
        seconds=60,
        description="every minute",
    )
    assert jid == "test-interval"
    assert scheduler.job_count >= 1
    jobs = scheduler.get_jobs()
    assert any(j["job_id"] == "test-interval" for j in jobs)


def test_schedule_cron_5_field_expression(scheduler: TaskScheduler):
    """A standard 5-field cron expression should produce a runnable job."""
    jid = scheduler.schedule_cron(
        job_id="test-cron",
        func=_noop,
        cron_expression="*/5 * * * *",
        description="every 5 minutes",
    )
    assert jid == "test-cron"
    job_info = next(j for j in scheduler.get_jobs() if j["job_id"] == "test-cron")
    assert job_info["cron"] == "*/5 * * * *"
    assert job_info["active"]


def test_cancel_job_removes_it(scheduler: TaskScheduler):
    scheduler.schedule_interval(job_id="cancel-me", func=_noop, seconds=10)
    assert scheduler.cancel_job("cancel-me") is True
    assert all(j["job_id"] != "cancel-me" for j in scheduler.get_jobs())


def test_cancel_unknown_job_returns_false(scheduler: TaskScheduler):
    assert scheduler.cancel_job("does-not-exist") is False


def test_job_count_tracks_state(scheduler: TaskScheduler):
    initial = scheduler.job_count
    scheduler.schedule_interval(job_id="c1", func=_noop, seconds=30)
    scheduler.schedule_interval(job_id="c2", func=_noop, seconds=30)
    assert scheduler.job_count == initial + 2
    scheduler.cancel_job("c1")
    assert scheduler.job_count == initial + 1
