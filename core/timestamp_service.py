from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional


class TimestampService:
    @staticmethod
    def parse(value: Any) -> Optional[dt.datetime]:
        if value is None:
            return None
        if isinstance(value, dt.datetime):
            return value
        if isinstance(value, (int, float)):
            return TimestampService._parse_numeric(value)
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text:
            return None
        if re.fullmatch(r"\d{12,}", text):
            return TimestampService._parse_numeric(int(text))
        iso = TimestampService._parse_iso(text)
        if iso is not None:
            return iso
        if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?", text):
            try:
                parts = text.split(":")
                hour = int(parts[0])
                minute = int(parts[1])
                second = 0
                if len(parts) > 2:
                    second = int(float(parts[2]))
                return dt.datetime(2000, 1, 1, hour, minute, second)
            except ValueError:
                return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
            try:
                return dt.datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_numeric(value: float) -> dt.datetime:
        if abs(value) >= 1_000_000_000_000:
            seconds = value / 1000.0
        else:
            seconds = value
        return dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc)

    @staticmethod
    def _parse_iso(text: str) -> Optional[dt.datetime]:
        patterns = [
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ]
        cleaned = text.replace("Z", "+00:00")
        try:
            return dt.datetime.fromisoformat(cleaned)
        except ValueError:
            pass
        for fmt in patterns:
            try:
                parsed = dt.datetime.strptime(text, fmt)
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=dt.timezone.utc)
                return parsed
            except ValueError:
                continue
        return None

    @staticmethod
    def as_local(value: Optional[dt.datetime], offset_hours: float = 0.0) -> Optional[dt.datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone(dt.timedelta(hours=offset_hours)))
        return value.astimezone(dt.timezone(dt.timedelta(hours=offset_hours)))

    @staticmethod
    def seconds_from_vtt(text: str) -> Optional[float]:
        match = re.fullmatch(r"(\d+):(\d+):(\d+)(?:\.(\d+))?", text)
        if not match:
            return None
        hours, minutes, seconds = map(int, match.group(1, 2, 3))
        fraction = 0.0
        if match.group(4):
            fraction = int((match.group(4) + "000")[:3]) / 1000.0
        return hours * 3600 + minutes * 60 + seconds + fraction
