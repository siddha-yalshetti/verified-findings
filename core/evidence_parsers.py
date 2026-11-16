from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from .timestamp_service import TimestampService


@dataclass
class EvidenceRecord:
    evidence_id: str
    source_file: str
    row_number: int
    raw: str
    parsed: Dict[str, Any] = field(default_factory=dict)
    timestamp: Any = None
    device: str | None = None
    source: str | None = None
    record_type: str = "raw"


class CameraCSVParser:
    @staticmethod
    def parse(path: str | Path) -> List[EvidenceRecord]:
        records: List[EvidenceRecord] = []
        text = Path(path).read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        for idx, raw_line in enumerate(lines, start=1):
            if not raw_line.strip():
                continue
            if raw_line.startswith("#PLEARUN") or raw_line.startswith("timestamp,"):
                continue
            values = next(csv.reader([raw_line]))
            if len(values) < 4:
                continue
            ts_raw, device, speed_mph, zone_mph = values[:4]
            records.append(
                EvidenceRecord(
                    evidence_id=f"camera-{idx}",
                    source_file=Path(path).name,
                    row_number=idx,
                    raw=raw_line,
                    parsed={"timestamp": ts_raw, "device": device, "speed_mph": speed_mph, "zone_mph": zone_mph},
                    timestamp=ts_raw,
                    device=device,
                    source="camera",
                    record_type="camera_row",
                )
            )
        return records


class OfficerNotesParser:
    @staticmethod
    def parse(path: str | Path) -> List[EvidenceRecord]:
        records: List[EvidenceRecord] = []
        with open(path, "r", encoding="cp1252", newline="") as fh:
            lines = fh.read().splitlines()
        if not lines:
            return records
        for idx, raw_line in enumerate(lines[1:], start=1):
            if not raw_line.strip():
                continue
            values = next(csv.reader([raw_line]))
            if len(values) < 4:
                continue
            rec_id, author, note, time_value = values[:4]
            records.append(
                EvidenceRecord(
                    evidence_id=f"notes-{idx}",
                    source_file=Path(path).name,
                    row_number=idx,
                    raw=raw_line,
                    parsed={"id": rec_id, "author": author, "note": note, "time": time_value},
                    timestamp=time_value,
                    device=author,
                    source="notes",
                    record_type="notes_row",
                )
            )
        return records


class DispatchJSONParser:
    @staticmethod
    def parse(path: str | Path) -> List[EvidenceRecord]:
        text = Path(path).read_text(encoding="utf-8")
        payload = json.loads(text)
        events = payload.get("export", {}).get("events", [])
        records: List[EvidenceRecord] = []
        events_match = re.search(r'"events"\s*:\s*\[', text)
        raw_events: List[str] = []
        if events_match:
            index = events_match.end()
            while index < len(text):
                while index < len(text) and (text[index].isspace() or text[index] == ","):
                    index += 1
                if index >= len(text) or text[index] == "]":
                    break
                if text[index] != "{":
                    break
                start = index
                depth = 0
                in_string = False
                escaped = False
                while index < len(text):
                    char = text[index]
                    if in_string:
                        if escaped:
                            escaped = False
                        elif char == "\\":
                            escaped = True
                        elif char == '"':
                            in_string = False
                    elif char == '"':
                        in_string = True
                    elif char == "{":
                        depth += 1
                    elif char == "}":
                        depth -= 1
                        if depth == 0:
                            index += 1
                            raw_events.append(text[start:index])
                            break
                    index += 1
                else:
                    break
        for idx, event in enumerate(events, start=1):
            raw = raw_events[idx - 1] if idx - 1 < len(raw_events) else json.dumps(event, ensure_ascii=False, indent=2)
            records.append(
                EvidenceRecord(
                    evidence_id=f"dispatch-{idx}",
                    source_file=Path(path).name,
                    row_number=idx,
                    raw=raw,
                    parsed=event,
                    timestamp=event.get("logged"),
                    device=event.get("unit"),
                    source="dispatch",
                    record_type="dispatch_event",
                )
            )
        return records


class BodycamVTTParser:
    @staticmethod
    def parse(path: str | Path) -> List[EvidenceRecord]:
        text = Path(path).read_bytes().decode("utf-8")
        blocks = re.split(r"(?:\r\n|\n)[ \t]*(?:\r\n|\n)|\r[ \t]*\r", text.strip("\ufeff\r\n"))
        records: List[EvidenceRecord] = []
        cue_index = 0
        for block in blocks:
            if not block.strip():
                continue
            lines = block.splitlines()
            timestamp_index = next(
                (index for index, line in enumerate(lines) if "-->" in line),
                None,
            )
            if timestamp_index is None or timestamp_index + 1 >= len(lines):
                continue
            timestamp_line = lines[timestamp_index].strip()
            cue_text = "\n".join(lines[timestamp_index + 1 :]).strip()
            start_seconds = None
            m = re.match(r"([^\s]+)\s+-->\s+([^\s]+)", timestamp_line)
            if m:
                start_seconds = TimestampService.seconds_from_vtt(m.group(1))
            cue_index += 1
            records.append(
                EvidenceRecord(
                    evidence_id=f"bodycam-{cue_index}",
                    source_file=Path(path).name,
                    row_number=cue_index,
                    raw=block,
                    parsed={"timestamp_line": timestamp_line, "start_seconds": start_seconds, "text": cue_text},
                    timestamp=start_seconds,
                    device="bodycam",
                    source="bodycam",
                    record_type="vtt_cue",
                )
            )
        return records
