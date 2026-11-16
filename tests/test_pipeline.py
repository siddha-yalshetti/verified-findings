from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.clock_sync import ClockSynchronizationEngine
from core.evidence_parsers import BodycamVTTParser, CameraCSVParser, DispatchJSONParser, OfficerNotesParser
from core.report_processor import ReportProcessor
from core.timestamp_service import TimestampService
from core.verification import CitationValidator, VerificationEngine
from plearun_cli import main, make_findings


ROOT = Path(__file__).resolve().parents[1]


class ClockSynchronizationTests(unittest.TestCase):
    @staticmethod
    def record(source, timestamp, event_type=None, text=""):
        parsed = {"type": event_type} if event_type else {"note": text}
        return SimpleNamespace(
            source=source,
            timestamp=timestamp,
            parsed=parsed,
            raw=text or event_type or "",
        )

    def test_estimates_offset_from_two_consistent_shared_events(self):
        evidence = [
            self.record("dispatch", 1000, event_type="911_call"),
            self.record("dispatch", 2000, event_type="unit_on_scene"),
            self.record("camera", 940, text="911 call"),
            self.record("camera", 1940, text="unit on scene"),
        ]

        offsets = ClockSynchronizationEngine().estimate_offsets(evidence)

        self.assertEqual(offsets, {"dispatch": 0.0, "camera": 60.0})

    def test_does_not_estimate_offset_from_one_anchor(self):
        evidence = [
            self.record("dispatch", 1000, event_type="911_call"),
            self.record("camera", 940, text="911 call"),
        ]

        self.assertNotIn("camera", ClockSynchronizationEngine().estimate_offsets(evidence))

    def test_rejects_inconsistent_clock_offset(self):
        evidence = [
            self.record("dispatch", 1000, event_type="911_call"),
            self.record("dispatch", 2000, event_type="unit_on_scene"),
            self.record("camera", 940, text="911 call"),
            self.record("camera", 2200, text="unit on scene"),
        ]

        self.assertNotIn("camera", ClockSynchronizationEngine().estimate_offsets(evidence))

    def test_normalizes_unix_milliseconds_as_seconds(self):
        normalized = ClockSynchronizationEngine.normalize(1772504040000)
        expected = TimestampService.parse(1772504040000).timestamp()

        self.assertEqual(normalized, expected)


class PipelineTests(unittest.TestCase):
    def test_cli_help_is_available(self):
        output = StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as result:
            main(["--help"])

        self.assertEqual(result.exception.code, 0)
        self.assertIn("Verify incident report claims", output.getvalue())

    def test_cli_reports_missing_input_path(self):
        error = StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit) as result:
            main(["missing-report.txt", "records"])

        self.assertEqual(result.exception.code, 2)
        self.assertIn("report is not a file", error.getvalue())

    def test_all_supported_evidence_parsers_return_records(self):
        records_dir = ROOT / "records"
        records = (
            CameraCSVParser.parse(records_dir / "camera_log.csv")
            + OfficerNotesParser.parse(records_dir / "notes_cp1252.csv")
            + DispatchJSONParser.parse(records_dir / "dispatch.json")
            + BodycamVTTParser.parse(records_dir / "bodycam_transcript.vtt")
        )

        self.assertTrue(records)
        self.assertEqual(
            {record.source for record in records},
            {"camera", "notes", "dispatch", "bodycam"},
        )

    def test_findings_have_required_shape_and_valid_citations(self):
        records_dir = ROOT / "records"
        report_path = ROOT / "reports" / "report_fictional_02.txt"
        findings = make_findings(report_path, records_dir)["findings"]

        self.assertTrue(findings)
        self.assertEqual(
            [finding["finding"] for finding in findings],
            ["not_settled", "not_settled", "match", "match", "not_checkable"],
        )
        for finding in findings:
            self.assertIn(finding["finding"], {"match", "conflict", "not_settled", "not_checkable"})
            self.assertIn("claim", finding)
            if finding["finding"] in {"match", "conflict"}:
                self.assertEqual(set(finding), {"claim", "finding", "cite", "quote"})
                self.assertIn("cite", finding)
                self.assertIn("quote", finding)
                self.assertTrue(
                    CitationValidator.validate(records_dir / finding["cite"]["file"], finding["quote"])
                )
            else:
                self.assertEqual(set(finding), {"claim", "finding"})
                self.assertNotIn("cite", finding)
                self.assertNotIn("quote", finding)

    def test_cp1252_citations_are_validated_using_source_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.csv"
            path.write_bytes(b"caf\xe9")
            self.assertTrue(CitationValidator.validate(path, "café"))

    def test_citation_must_come_from_the_cited_row(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.txt"
            path.write_text("row one\nrow two", encoding="utf-8")
            self.assertFalse(CitationValidator.validate(path, "row one", "row two"))

    def test_dispatch_parser_preserves_nested_event_objects(self):
        source = (
            '{\n  "export": {"events": [\n'
            '    {"id": "D-1", "type": "unit_on_scene", "extra": {"unit": "L-12"}}\n'
            "  ]}\n}"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dispatch.json"
            path.write_text(source, encoding="utf-8")
            record = DispatchJSONParser.parse(path)[0]

        self.assertIn('"extra": {"unit": "L-12"}', record.raw)
        self.assertIn(record.raw, source)

    def test_webvtt_parser_handles_cue_identifiers_and_overlaps(self):
        source = (
            "WEBVTT\r\n\r\n"
            "cue-a\r\n00:00:00.000 --> 00:00:04.000\r\nFirst cue\r\n\r\n"
            "cue-b\r\n00:00:03.500 --> 00:00:07.000\r\nSecond cue\r\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bodycam.vtt"
            path.write_bytes(source.encode("utf-8"))
            records = BodycamVTTParser.parse(path)

        self.assertEqual([record.row_number for record in records], [1, 2])
        self.assertEqual(records[0].parsed["start_seconds"], 0.0)
        self.assertEqual(records[1].parsed["start_seconds"], 3.5)
        self.assertTrue(all(record.raw in source for record in records))

    def test_unrelated_event_text_does_not_support_claim(self):
        claim = ReportProcessor.extract_claims("A unit was dispatched to the location.")[0]
        evidence = [
            SimpleNamespace(
                raw='{"type":"unit_on_scene","logged":"21:17"}',
                source="dispatch",
                source_file="dispatch.json",
                row_number=1,
                parsed={"type": "unit_on_scene"},
            )
        ]

        with tempfile.TemporaryDirectory() as directory:
            result = VerificationEngine.verify(claim, evidence, directory)

        self.assertIn(result["finding"], {"not_settled", "not_checkable"})

    def test_compound_speed_claim_needs_matching_claim_time(self):
        claim = ReportProcessor.extract_claims(
            "The sedan was at mile marker 4 at about 21:14, travelling 58 mph."
        )[0]
        evidence = [
            SimpleNamespace(
                raw="00:00:00.000 --> 00:00:04.000\nOfficer Lee: 58 in a 45.",
                source="bodycam",
                source_file="bodycam.vtt",
                row_number=1,
                parsed={"text": "Officer Lee: 58 in a 45."},
            )
        ]

        with tempfile.TemporaryDirectory() as directory:
            result = VerificationEngine.verify(claim, evidence, directory)

        self.assertEqual(result["finding"], "not_settled")

    def test_unaligned_camera_clock_cannot_create_speed_conflict(self):
        claim = ReportProcessor.extract_claims(
            "The sedan was observed at about 21:14, travelling 58 mph."
        )[0]
        camera = SimpleNamespace(
            raw="2026-03-02T21:10:21-05:00,CAM-03,39,45",
            source="camera",
            timestamp="2026-03-02T21:10:21-05:00",
            parsed={"speed_mph": "39", "zone_mph": "45"},
        )

        self.assertEqual(VerificationEngine._record_supports_speed(claim, camera), "unknown")

    def test_relative_stop_interval_requires_both_events_and_plausible_elapsed_time(self):
        claim = ReportProcessor.extract_claims(
            "Dispatch records show a unit on scene roughly 2 minutes after the stop."
        )[0]
        scene = SimpleNamespace(
            raw='{"type":"unit_on_scene","logged":"2026-03-02T21:17:19-05:00"}',
            parsed={"type": "unit_on_scene", "logged": "2026-03-02T21:17:19-05:00"},
        )
        stop = SimpleNamespace(
            raw="00:00:06.000 --> 00:00:12.000\nOfficer Lee: Pulling in at the lot, about 21:16.",
            parsed={"text": "Officer Lee: Pulling in at the lot, about 21:16."},
        )
        late_scene = SimpleNamespace(
            raw='{"type":"unit_on_scene","logged":"2026-03-02T21:20:30-05:00"}',
            parsed={"type": "unit_on_scene", "logged": "2026-03-02T21:20:30-05:00"},
        )

        self.assertEqual(
            VerificationEngine._record_supports_relative_stop_time(claim, scene, [scene, stop]),
            "support",
        )
        self.assertEqual(
            VerificationEngine._record_supports_relative_stop_time(claim, late_scene, [late_scene, stop]),
            "unknown",
        )


if __name__ == "__main__":
    unittest.main()
