from app import history


def test_empty_by_default():
    assert history.get_all() == []


def test_returns_newest_first_with_incrementing_ids():
    history.record("first", "SELECT 1", 1, 0.9)
    history.record("second", "SELECT 2", 2, 0.8)
    entries = history.get_all()
    assert [e["question"] for e in entries] == ["second", "first"]
    assert [e["id"] for e in entries] == [2, 1]


def test_limit_keeps_the_most_recent_entries():
    for i in range(5):
        history.record(f"q{i}", "SELECT 1", 1, 1.0)
    assert [e["question"] for e in history.get_all(limit=2)] == ["q4", "q3"]
