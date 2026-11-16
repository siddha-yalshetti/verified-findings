# Verified Findings

An offline Python CLI that checks report claims against camera, dispatch, officer-note, and body-camera records. It uses no network, external service, or third-party dependency. `mock_llm.py` is supplied as an optional interface example and is not called by this implementation.

## Run

From the project directory:

```powershell
python plearun_cli.py reports/report_fictional_02.txt records
python -m unittest discover -s tests -v
```

The CLI prints the required JSON to stdout. To save it, append `> findings.json`. `make test` is also available where GNU Make is installed. A sample result is included in [`findings.json`](./findings.json).

## Design

1. Split the report into sentence-level claims and extract useful numbers, times, and keywords.
2. Parse each supported evidence format into records carrying the exact source text, filename, row/cue number, and parsed fields.
3. Rank records as candidates, apply conservative claim-specific checks, and validate every citation against both its record and source file before emitting a match or conflict.
4. Estimate clock offsets only from at least two shared, recognizable events whose offsets agree within 30 seconds. Otherwise, leave that source unaligned.

The three hardest decisions were: preserving citation fidelity across BOM, CP1252, nested JSON, and WebVTT; avoiding a “match” when a compound claim has only partial support; and requiring repeated, consistent anchors before aligning unsynchronized clocks. Relative-time claims are checked against both the event and stop timestamps rather than inferred from a single record.

## Limitations

Language and event matching are rule-based, not general natural-language understanding. Ambiguous, unsupported, or only partially supported claims may be `not_settled` or `not_checkable`; the tool favors that over an unjustified conflict. Clock offsets cannot be estimated without enough recognizable shared events. Real records with undocumented time zones, vague locations, unusual encodings, or novel formats would need additional parsers and validation.

## Tools

Python standard library, VS Code, and Copilot in VS Code were used for implementation and testing; the supplied candidate pack provides the requirements and fictional fixtures. All runs and tests are local.
