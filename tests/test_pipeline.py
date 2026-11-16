import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.clock_sync import ClockSynchronizationEngine
from core.evidence_parsers import BodycamVTTParser, CameraCSVParser, DispatchJSONParser, OfficerNotesParser
from core.report_processor import ReportProcessor
from core.timestamp_service import TimestampService
from core.verification import CitationValidator, VerificationEngine
from plearun_cli import make_findings


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
        for finding in findings:
            self.assertIn(finding["finding"], {"match", "conflict", "not_settled", "not_checkable"})
            self.assertIn("claim", finding)
            if finding["finding"] in {"match", "conflict"}:
                self.assertIn("cite", finding)
                self.assertIn("quote", finding)
                self.assertTrue(
                    CitationValidator.validate(records_dir / finding["cite"]["file"], finding["quote"])
                )
            else:
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


if __name__ == "__main__":
    unittest.main()
