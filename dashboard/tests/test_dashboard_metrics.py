from app.views.observability import FLAGGED_SHARE_QUERY
from app.views.courses import _count_or_unavailable
from app.views.overview import CHECKIN_STATUSES, _flagged_share


def test_overview_flagged_share_requires_complete_nonempty_counts():
    counts = {status: 0 for status in CHECKIN_STATUSES}
    counts["flagged"] = 3
    counts["approved"] = 7

    assert _flagged_share(counts) == 0.3
    assert _flagged_share({}) is None
    assert _flagged_share({**counts, "pending": None}) is None
    assert _flagged_share({**counts, "pending": True}) is None
    assert _flagged_share({**counts, "pending": -1}) is None
    assert _flagged_share({status: 0 for status in CHECKIN_STATUSES}) is None


def test_observability_query_matches_fifteen_minute_flagged_share():
    assert 'decision="flagged"' in FLAGGED_SHARE_QUERY
    assert "[15m]" in FLAGGED_SHARE_QUERY
    assert "clamp_min" in FLAGGED_SHARE_QUERY


def test_missing_course_counts_are_not_reported_as_zero():
    assert _count_or_unavailable(0) == 0
    assert _count_or_unavailable(12) == 12
    assert _count_or_unavailable(None) == "Unavailable"
    assert _count_or_unavailable(True) == "Unavailable"
    assert _count_or_unavailable(-1) == "Unavailable"
