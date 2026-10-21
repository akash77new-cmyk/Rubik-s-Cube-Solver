"""Analytics: the confidence metric is a plain running mean, named honestly."""

from backend.db import connect
from backend.services.analytics import AnalyticsStore


def test_average_confidence_is_the_mean_of_samples():
    store = AnalyticsStore(connect("sqlite://"))
    store.note_detection_confidence(0.5)
    store.note_detection_confidence(1.0)

    assert store.average_confidence == 0.75
    summary = store.summary()
    assert summary["averageConfidence"] == 0.75
    # The old key claimed to be "accuracy"; no metric may claim that any more.
    assert not any("accuracy" in key.lower() for key in summary)
