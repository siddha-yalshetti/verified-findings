from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Claim:
    original: str
    claim_type: str
    numbers: List[float]
    times: List[str]
    keywords: List[str]


class ReportProcessor:
    @staticmethod
    def split_claims(report_text: str) -> List[str]:
        text = report_text.strip()
        if not text:
            return []
        sentences = re.split(r"(?<=[.!?])\s+", text)
        cleaned = [s.strip() for s in sentences if s and s.strip()]
        return cleaned

    @staticmethod
    def extract_claims(report_text: str) -> List[Claim]:
        claims: List[Claim] = []
        for sentence in ReportProcessor.split_claims(report_text):
            numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", sentence)]
            times = re.findall(r"\b(?:around|about|at|by|roughly|after)\s*\d{1,2}:\d{2}(?::\d{2})?\b|\b\d{1,2}:\d{2}(?::\d{2})?\b", sentence)
            words = re.findall(r"[A-Za-z][A-Za-z'-]+", sentence.lower())
            claim_type = "event"
            if re.search(r"\b(?:mph|mph\.|miles per hour)\b|\bposted\s+\d+\b", sentence, re.I):
                claim_type = "speed"
            elif re.search(r"\d{1,2}:\d{2}(?::\d{2})?", sentence):
                claim_type = "time"
            elif re.search(r"\b(?:only|single|one)\b.*\b(?:car|vehicle|lane)\b|\b(?:car|vehicle)\b.*\b(?:only|single|one)\b", sentence, re.I):
                claim_type = "count"
            elif re.search(r"\b(?:mile marker|lot|route|near|at|outside|inside|at the)\b", sentence, re.I):
                claim_type = "location"
            elif re.search(r"\b(?:logged|stopped|observed|pulled|scene|on scene|weaving|call)\b", sentence, re.I):
                claim_type = "event"
            claims.append(Claim(original=sentence, claim_type=claim_type, numbers=numbers, times=times, keywords=words))
        return claims
