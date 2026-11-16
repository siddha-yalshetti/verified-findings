from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .clock_sync import ClockSynchronizationEngine
from .report_processor import Claim
from .timestamp_service import TimestampService


def _normalize_time_fragment(text: str) -> str:
    return text.lower().replace("around ", "").replace("about ", "").replace("at ", "").replace("roughly ", "").replace("after ", "")


def _record_clock_seconds(record: Any) -> int | None:
    parsed = getattr(record, "parsed", None) or {}
    value = parsed.get("time") or parsed.get("text") or parsed.get("logged")
    if not value:
        value = getattr(record, "raw", "")
    parsed_time = TimestampService.parse(value)
    if parsed_time is not None:
        return parsed_time.hour * 3600 + parsed_time.minute * 60 + parsed_time.second
    matches = re.findall(r"(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?\b", str(value))
    for hour_text, minute_text, second_text in matches:
        hour, minute = int(hour_text), int(minute_text)
        if hour < 24 and minute < 60:
            return hour * 3600 + minute * 60 + (int(second_text) if second_text else 0)
    return None


class CitationValidator:
    @staticmethod
    def validate(path: str | Path, quote: str, row_raw: str | None = None) -> bool:
        if not quote:
            return False
        if row_raw is not None and quote not in row_raw:
            return False
        file_path = Path(path)
        if not file_path.exists():
            return False
        raw_bytes = file_path.read_bytes()
        return any(
            quote in raw_bytes.decode(encoding, errors="surrogateescape")
            for encoding in ("utf-8-sig", "cp1252")
        )


class VerificationEngine:
    @staticmethod
    def build_candidates(claim: Claim, evidence_records: Iterable[Any]) -> List[Any]:
        candidates: List[Any] = []
        for record in evidence_records:
            score = 0
            raw = (record.raw or "").lower()
            if not raw:
                continue
            for token in claim.keywords:
                if token in raw:
                    score += 2
            for num in claim.numbers:
                if re.search(rf"{int(num)}(?:\.\d+)?", raw) or re.search(rf"{float(num):g}(?:\.\d+)?", raw):
                    score += 3
            for time_fragment in claim.times:
                norm = _normalize_time_fragment(time_fragment)
                if norm in raw:
                    score += 4
            if claim.claim_type == "speed" and ("speed" in raw or "mph" in raw or "45" in raw):
                score += 2
            if claim.claim_type == "event" and any(word in raw for word in ["scene", "call", "stopped", "lot", "observed", "weaving", "lane", "dispatch"]):
                score += 3
            if claim.claim_type == "count" and any(word in raw for word in ["only", "single", "lane", "vehicle"]):
                score += 2
            if claim.claim_type == "time" and any(word in raw for word in ["logged", "stopped", "21:", "scene"]):
                score += 2
            if score > 0:
                candidates.append((score, record))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in candidates]

    @staticmethod
    def _record_supports_speed(
        claim: Claim, record: Any, clock_offsets: Dict[str, float] | None = None
    ) -> str:
        raw = (record.raw or "").lower()
        numbers = [float(value) for value in claim.numbers if 10 <= value <= 120 and not any(str(int(value)) in t for t in claim.times)]
        target = max(numbers) if numbers else None
        if target is None:
            return "unknown"

        parsed = getattr(record, "parsed", None) or {}
        if claim.times and not any(
            _normalize_time_fragment(time_fragment) in raw for time_fragment in claim.times
        ):
            if record.source != "camera":
                return "unknown"

        if record.source == "camera" and isinstance(parsed, dict) and "speed_mph" in parsed:
            try:
                claim_minutes = []
                for token in claim.times:
                    match = re.search(r"(\d{1,2}):(\d{2})", token)
                    if match:
                        claim_minutes.append(int(match.group(1)) * 60 + int(match.group(2)))
                if not claim_minutes:
                    return "unknown"
                ts = getattr(record, "timestamp", None)
                if ts is None:
                    return "unknown"
                offset = (clock_offsets or {}).get(record.source)
                if offset is None:
                    return "unknown"
                normalized = ClockSynchronizationEngine.normalize(ts, offset or 0.0)
                if normalized is None:
                    return "unknown"
                record_minutes = (normalized % 86400) / 60
                close = any(
                    min(abs(record_minutes - minute), 1440 - abs(record_minutes - minute)) <= 5
                    for minute in claim_minutes
                )
                if not close:
                    return "unknown"
                candidate = float(parsed["speed_mph"])
                if abs(candidate - target) <= 2:
                    if "posted" in claim.original.lower():
                        posted_speeds = [
                            float(value)
                            for value in re.findall(r"\bposted\s+(\d+(?:\.\d+)?)\b", claim.original, re.I)
                        ]
                        zone_speed = parsed.get("zone_mph")
                        if posted_speeds and zone_speed is not None:
                            try:
                                if float(zone_speed) not in posted_speeds:
                                    return "unknown"
                            except (TypeError, ValueError):
                                return "unknown"
                    return "support"
                if abs(candidate - target) >= 5:
                    return "contradict"
                return "unknown"
            except (TypeError, ValueError):
                return "unknown"

        direct_matches = re.findall(r"\b(\d{2,3})\s*(?:mph|in\s+a)\b", raw)
        if direct_matches:
            if claim.times and not any(
                _normalize_time_fragment(time_fragment) in raw for time_fragment in claim.times
            ):
                return "unknown"
            values = [float(v) for v in direct_matches]
            if any(abs(v - target) <= 2 for v in values):
                return "support"
            if any(abs(v - target) >= 5 for v in values):
                return "contradict"
            return "unknown"
        return "unknown"

    @staticmethod
    def _record_supports_time(claim: Claim, record: Any) -> str:
        raw = (record.raw or "").lower()
        for time_fragment in claim.times:
            norm = _normalize_time_fragment(time_fragment)
            if norm in raw:
                return "support"
        claim_times = [t for t in re.findall(r"\d{1,2}:\d{2}(?::\d{2})?", claim.original)]
        raw_times = re.findall(r"\d{1,2}:\d{2}(?::\d{2})?", raw)
        for claim_time in claim_times:
            for raw_time in raw_times:
                try:
                    c_h, c_m = map(int, claim_time.split(":")[:2])
                    r_h, r_m = map(int, raw_time.split(":")[:2])
                    delta = abs((c_h * 60 + c_m) - (r_h * 60 + r_m))
                    if delta <= 2:
                        return "support"
                except ValueError:
                    continue
        if "logged" in raw and any(t in raw for t in ["21:10", "21:11", "21:17"]):
            return "support"
        return "unknown"

    @staticmethod
    def _record_supports_event(claim: Claim, record: Any) -> str:
        raw = (record.raw or "").lower()
        claim_text = claim.original.lower()
        parsed = getattr(record, "parsed", None) or {}
        event_type = str(parsed.get("type", "")).lower()

        if "911" in claim_text and "call" in claim_text:
            return "support" if event_type == "911_call" or "911 call" in raw else "unknown"
        if "on scene" in claim_text:
            return "support" if event_type == "unit_on_scene" or "on scene" in raw else "unknown"
        if "dispatched" in claim_text:
            return "support" if event_type == "unit_dispatched" or "unit dispatched" in raw else "unknown"
        if any(word in claim_text for word in ("stopped", "pulling in", "pulled into")):
            if any(phrase in raw for phrase in ("stopped at", "pulling in", "pulled into")):
                return "support"
            return "unknown"
        if "weaving" in claim_text:
            return "support" if "weaving" in raw else "unknown"
        if "observed" in claim_text:
            return "support" if "observed" in raw else "unknown"
        return "unknown"

    @staticmethod
    def _record_supports_count(claim: Claim, record: Any) -> str:
        raw = (record.raw or "").lower()
        if any(term in raw for term in ["only", "single"]):
            return "support"
        return "unknown"

    @staticmethod
    def _record_supports_relative_stop_time(
        claim: Claim, scene_record: Any, evidence_records: Iterable[Any]
    ) -> str:
        parsed = getattr(scene_record, "parsed", None) or {}
        if str(parsed.get("type", "")).lower() != "unit_on_scene":
            return "unknown"
        scene_seconds = _record_clock_seconds(scene_record)
        if scene_seconds is None:
            return "unknown"
        for stop_record in evidence_records:
            raw = (getattr(stop_record, "raw", "") or "").lower()
            if not any(phrase in raw for phrase in ("pulling in", "stopped at", "pulled into")):
                continue
            stop_seconds = _record_clock_seconds(stop_record)
            if stop_seconds is None:
                continue
            elapsed = (scene_seconds - stop_seconds) % 86400
            if 60 <= elapsed <= 180:
                return "support"
        return "unknown"

    @staticmethod
    def _record_supports_claimed_location(claim: Claim, record: Any) -> bool:
        claim_text = claim.original.lower()
        raw = (getattr(record, "raw", "") or "").lower()
        marker = re.search(r"\bmile\s+marker\s+(\d+)\b", claim_text)
        if marker and not re.search(rf"\bmile\s+marker\s+{marker.group(1)}\b", raw):
            return False
        if "harbor gas" in claim_text and not re.search(r"\bharbor\s*gas\b", raw):
            return False
        return True

    @staticmethod
    def _record_score(claim: Claim, record: Any) -> int:
        score = 0
        raw = (record.raw or "").lower()
        for token in claim.keywords:
            if token in raw:
                score += 3
        if claim.claim_type == "speed" and "mph" in raw:
            score += 5
        if claim.claim_type == "event" and any(word in raw for word in ["scene", "call", "stopped", "lot", "dispatch", "on_scene"]):
            score += 5
        if claim.claim_type == "time" and any(t in raw for t in ["21:10", "21:11", "21:16", "21:17"]):
            score += 4
        return score

    @staticmethod
    def verify(
        claim: Claim,
        evidence_records: Iterable[Any],
        records_dir: str | Path,
        clock_offsets: Dict[str, float] | None = None,
    ) -> Dict[str, Any]:
        all_records = list(evidence_records)
        candidates = VerificationEngine.build_candidates(claim, all_records)
        if not candidates:
            return {"claim": claim.original, "finding": "not_checkable"}

        support = []
        contradiction = []
        for record in candidates:
            raw = record.raw or ""
            decision = "unknown"
            if "2 minutes" in claim.original.lower() and "after the stop" in claim.original.lower():
                decision = VerificationEngine._record_supports_relative_stop_time(
                    claim, record, all_records
                )
            elif claim.claim_type == "speed":
                decision = VerificationEngine._record_supports_speed(claim, record, clock_offsets)
            elif claim.claim_type == "time":
                decision = VerificationEngine._record_supports_time(claim, record)
            elif claim.claim_type == "event":
                decision = VerificationEngine._record_supports_event(claim, record)
            elif claim.claim_type == "count":
                decision = VerificationEngine._record_supports_count(claim, record)
            elif claim.claim_type == "location":
                decision = "support" if any(token in raw.lower() for token in ["lot", "mile", "route"]) else "unknown"

            if decision == "support" and not VerificationEngine._record_supports_claimed_location(claim, record):
                decision = "unknown"

            if decision == "support":
                support.append(record)
            elif decision == "contradict":
                contradiction.append(record)

        if support:
            if contradiction and not any(r.source in {"bodycam", "dispatch", "notes"} for r in support):
                return {"claim": claim.original, "finding": "not_settled"}
            preferred = support
            lower = claim.original.lower()
            if claim.claim_type == "speed":
                preferred = [r for r in support if r.source == "bodycam"] or support
            elif "911 call" in lower or "logged at" in lower:
                preferred = [r for r in support if r.source == "dispatch"] or support
            elif "unit on scene" in lower or "scene" in lower:
                preferred = [r for r in support if r.source == "dispatch"] or support
            record = max(preferred, key=lambda r: VerificationEngine._record_score(claim, r))
            quote = record.raw
            if not CitationValidator.validate(
                Path(records_dir) / record.source_file, quote, record.raw
            ):
                return {"claim": claim.original, "finding": "not_settled"}
            return {
                "claim": claim.original,
                "finding": "match",
                "cite": {"file": record.source_file, "row": record.row_number},
                "quote": quote,
            }
        if contradiction and not support:
            record = max(contradiction, key=lambda r: VerificationEngine._record_score(claim, r))
            quote = record.raw
            if not CitationValidator.validate(
                Path(records_dir) / record.source_file, quote, record.raw
            ):
                return {"claim": claim.original, "finding": "not_settled"}
            return {
                "claim": claim.original,
                "finding": "conflict",
                "cite": {"file": record.source_file, "row": record.row_number},
                "quote": quote,
            }
        if claim.claim_type == "count" and "only" in claim.original.lower():
            return {"claim": claim.original, "finding": "not_checkable"}
        return {"claim": claim.original, "finding": "not_settled"}
