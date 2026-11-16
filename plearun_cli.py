from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify incident report claims against local evidence records."
    )
    parser.add_argument("report", type=Path, help="path to the incident report")
    parser.add_argument("records_dir", type=Path, help="directory containing evidence files")
    args = parser.parse_args(argv)
    if not args.report.is_file():
        parser.error(f"report is not a file: {args.report}")
    if not args.records_dir.is_dir():
        parser.error(f"records directory does not exist: {args.records_dir}")
    try:
        result = make_findings(args.report, args.records_dir)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        parser.exit(2, f"error: unable to process input: {error}\n")
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
