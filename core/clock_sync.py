from __future__ import annotations

import calendar
import datetime as dt
import statistics
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

from .timestamp_service import TimestampService


class ClockSynchronizationEngine:
    def __init__(self, minimum_anchors: int = 2, maximum_spread_seconds: float = 30.0):
        self.minimum_anchors = minimum_anchors
        self.maximum_spread_seconds = maximum_spread_seconds

    @staticmethod
    def _timestamp_seconds(record: Any) -> Optional[float]:
        value = getattr(record, "timestamp", None)
        if isinstance(value, (int, float)) and abs(value) < 1_000_000_000_000:
            return float(value)

        parsed = TimestampService.parse(value)
        if parsed is None:
            return None
        if parsed.tzinfo is not None:
            return parsed.timestamp()
        return calendar.timegm(parsed.timetuple()) + parsed.microsecond / 1_000_000

    @staticmethod
    def _event_labels(record: Any) -> set[str]:
        parsed = getattr(record, "parsed", None) or {}
        event_type = str(parsed.get("type", "")).lower()
        text = " ".join(
            str(value)
            for value in (parsed.get("note", ""), parsed.get("text", ""), getattr(record, "raw", ""))
        ).lower()
        labels: set[str] = set()

        if event_type == "911_call" or ("911" in text and "call" in text):
            labels.add("911_call")
        if event_type == "unit_on_scene" or "unit on scene" in text or "on scene" in text:
            labels.add("unit_on_scene")
        if event_type == "unit_dispatched" or "unit dispatched" in text or "dispatched" in text:
            labels.add("unit_dispatched")
        if any(phrase in text for phrase in ("stopped at", "pulling in", "stop at")):
            labels.add("stop_at_lot" if any(word in text for word in ("lot", "gas")) else "stop")
        if "weaving" in text:
            labels.add("weaving")
        return labels

    def estimate_offsets(self, evidence_records: Iterable[Any]) -> Dict[str, float]:
        anchors: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
        for record in evidence_records:
            source = getattr(record, "source", None)
            timestamp = self._timestamp_seconds(record)
            if not source or timestamp is None:
                continue
            for label in self._event_labels(record):
                anchors[source][label].append(timestamp)

        if not anchors:
            return {}

        reference = "dispatch" if "dispatch" in anchors else max(
            anchors, key=lambda source: len(anchors[source])
        )
        offsets: Dict[str, float] = {reference: 0.0}
        reference_anchors = anchors[reference]

        for source, source_anchors in anchors.items():
            if source == reference:
                continue
            differences = [
                statistics.median(reference_anchors[label])
                - statistics.median(source_anchors[label])
                for label in reference_anchors.keys() & source_anchors.keys()
            ]
            if len(differences) < self.minimum_anchors:
                continue
            offset = statistics.median(differences)
            if max(abs(value - offset) for value in differences) <= self.maximum_spread_seconds:
                offsets[source] = offset
        return offsets

    def choose_reliable_offsets(self, evidence_records: Iterable[Any]) -> Dict[str, float]:
        return self.estimate_offsets(evidence_records)

    @staticmethod
    def normalize(timestamp_value: Any, offset_seconds: float = 0.0) -> Optional[float]:
        if isinstance(timestamp_value, (int, float)) and abs(timestamp_value) < 1_000_000_000_000:
            return float(timestamp_value) + offset_seconds
        parsed = TimestampService.parse(timestamp_value)
        if parsed is None:
            return None
        if parsed.tzinfo is not None:
            timestamp = parsed.timestamp()
        else:
            timestamp = calendar.timegm(parsed.timetuple()) + parsed.microsecond / 1_000_000
        return timestamp + offset_seconds
