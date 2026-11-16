import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SampleData(unittest.TestCase):
    def test_camera_log_has_marker_and_header(self):
        raw = (ROOT / "records" / "camera_log.csv").read_text(encoding="utf-8-sig").splitlines()
        self.assertTrue(raw[0].startswith("#PLEARUN"))
        self.assertEqual(raw[1], "timestamp,device,speed_mph,zone_mph")

    def test_dispatch_json_parses(self):
        json.loads((ROOT / "records" / "dispatch.json").read_text(encoding="utf-8"))

    def test_notes_decode_as_cp1252(self):
        (ROOT / "records" / "notes_cp1252.csv").read_bytes().decode("cp1252")

    def test_transcript_is_webvtt(self):
        self.assertTrue((ROOT / "records" / "bodycam_transcript.vtt").read_text(encoding="utf-8").startswith("WEBVTT"))


if __name__ == "__main__":
    unittest.main()
