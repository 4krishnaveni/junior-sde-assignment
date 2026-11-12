
from datetime import datetime, timezone

from pipeline.derive import (
    BUCKET_YET_TO_REACH_OUT,
    BUCKET_COMPLETED,
    BUCKET_TELEPHONY_FAILED,
    BUCKET_DIALED,
    CallSummary,
    DispositionInfo,
    effective_disposition,
    compute_bucket,
)


def test_override_beats_later_set():
    sets = [
        (datetime(2026, 1, 1, 10, tzinfo=timezone.utc), "event_2", "SUCCESS")
    ]
    overrides = [
        (datetime(2026, 1, 1, 9, tzinfo=timezone.utc), "event_1", "REJECTED")
    ]

    assert effective_disposition(sets, overrides) == "REJECTED"


def test_latest_override_wins():
    overrides = [
        (datetime(2026, 1, 1, 10, tzinfo=timezone.utc), "event_1", "REJECTED"),
        (datetime(2026, 1, 1, 11, tzinfo=timezone.utc), "event_2", "SUCCESS"),
    ]

    assert effective_disposition([], overrides) == "SUCCESS"


def test_override_uses_time_not_arrival_order():
    overrides = [
        (datetime(2026, 1, 1, 12, tzinfo=timezone.utc), "event_1", "SUCCESS"),
        (datetime(2026, 1, 1, 10, tzinfo=timezone.utc), "event_2", "REJECTED"),
    ]

    assert effective_disposition([], overrides) == "SUCCESS"


def test_bucket_yet_to_reach_out():
    assert compute_bucket([], {}) == BUCKET_YET_TO_REACH_OUT


def test_bucket_completed():
    catalogue = {"SUCCESS": DispositionInfo(True, True)}
    calls = [
        CallSummary("c1", datetime.now(timezone.utc), True, False, "SUCCESS")
    ]

    assert compute_bucket(calls, catalogue) == BUCKET_COMPLETED


def test_bucket_telephony_failed():
    calls = [
        CallSummary("c1", datetime.now(timezone.utc), False, True, None),
        CallSummary("c2", datetime.now(timezone.utc), False, True, None),
    ]

    assert compute_bucket(calls, {}) == BUCKET_TELEPHONY_FAILED


def test_bucket_dialed():
    calls = [
        CallSummary("c1", datetime.now(timezone.utc), True, False, None)
    ]

    assert compute_bucket(calls, {}) == BUCKET_DIALED
