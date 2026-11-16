# Verified Findings

Tools used: Python standard library for implementation and tests; VS Code and Copilot in VS Code for editing and reasoning; the supplied candidate pack for fixtures and requirements; and the local shell for running the CLI and tests. The implementation is entirely offline and does not call any external service. `mock_llm.py` is not used by the CLI.

This project checks incident-report claims against machine evidence without network access. The verifier is deliberately conservative: if the evidence is weak or ambiguous, it prefers `not_settled` or `not_checkable` over a risky `conflict`.

## How it works

- The report is split into sentence-level claims and tagged by type such as speed, time, event, or count.
- Each record file is normalized into evidence objects that preserve the exact raw text, row or cue number, source filename, and timestamp metadata.
- The clock synchronizer looks for repeated, clearly labeled events in different sources. It estimates an offset only with at least two shared events whose offsets agree within 30 seconds; otherwise that source is left unaligned.
- Timestamps support Unix-millisecond, ISO-8601, local-time, and WebVTT values while leaving original raw strings intact for citation validation.
- Candidate evidence is ranked by keywords, numeric matches, and time proximity before any finding is produced.
- Findings are only emitted when the evidence is direct and reliable; otherwise the code falls back to `not_settled` and `not_checkable`.
- Every match or conflict is re-checked against the original source text to confirm the citation exists and the quote is an exact substring before final output.

## Three hardest decisions

1. Clock drift and device offsets. The tool requires two consistent shared-event anchors and refuses alignment when there is not enough agreement.
2. False conflicts. A noisy or unrelated machine record should not trigger a conflict when one direct piece of evidence is very strong. The verifier prefers high-quality direct support and ignores weak contradictions.
3. Messy file handling. The project is built to tolerate a BOM-prefixed CSV, Windows-1252 text, nested JSON events, and WebVTT cues while preserving exact raw strings for verification.

## What it gets wrong

It is conservative by design, so it can return `not_settled` instead of a stronger but less certain finding. Its event and claim language matching is rule-based, not a general natural-language understanding system. It also does not invent missing evidence or create facts that are not in the source records.

## What would fail first on real records

The first brittle cases are vague narrative claims without direct numbers, repeated event names over long logs, and records with contradictory time zones or deceptive timestamps. Those situations usually trigger uncertainty instead of a reckless conflict. The offset estimator also cannot align a source without at least two recognizable shared events.

## Run and test

From this directory, run `python plearun_cli.py reports/report_fictional_02.txt records`. Run tests with `python -m unittest discover -s tests -v` (or `make test` where `make` is installed).
