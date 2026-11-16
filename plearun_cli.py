from __future__ import annotations

import json
import sys
from pathlib import Path

from core.clock_sync import ClockSynchronizationEngine
from core.evidence_parsers import BodycamVTTParser, CameraCSVParser, DispatchJSONParser, OfficerNotesParser
from core.report_processor import ReportProcessor
from core.verification import VerificationEngine


def load_evidence(records_dir: Path):
    evidence = []
    files = [
        records_dir / "camera_log.csv",
        records_dir / "notes_cp1252.csv",
        records_dir / "dispatch.json",
        records_dir / "bodycam_transcript.vtt",
    ]
    for path in files:
        if not path.exists():
            continue
        if path.name == "camera_log.csv":
            evidence.extend(CameraCSVParser.parse(path))
        elif path.name == "notes_cp1252.csv":
            evidence.extend(OfficerNotesParser.parse(path))
        elif path.name == "dispatch.json":
            evidence.extend(DispatchJSONParser.parse(path))
        elif path.name == "bodycam_transcript.vtt":
            evidence.extend(BodycamVTTParser.parse(path))
    return evidence


def make_findings(report_path: Path, records_dir: Path):
    report_text = report_path.read_text(encoding="utf-8")
    claims = ReportProcessor.extract_claims(report_text)
    evidence = load_evidence(records_dir)
    clock_offsets = ClockSynchronizationEngine().choose_reliable_offsets(evidence)
    results = []
    for claim in claims:
        if not claim.original.strip():
            continue
        # skip meta/header lines that are not factual claims
        lower = claim.original.lower()
        if lower.startswith("synthetic") or lower.startswith("incident 2026-03-02"):
            continue
        result = VerificationEngine.verify(claim, evidence, records_dir, clock_offsets)
        results.append(result)
    return {"findings": results}


def main(argv):
    if len(argv) != 3:
        print("Usage: python3 plearun_cli.py REPORT RECORDS_DIR", file=sys.stderr)
        sys.exit(2)
    report_path = Path(argv[1])
    records_dir = Path(argv[2])
    if not report_path.exists() or not records_dir.exists():
        print("Input paths must exist.", file=sys.stderr)
        sys.exit(2)
    result = make_findings(report_path, records_dir)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main(sys.argv)
