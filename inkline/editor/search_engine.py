from __future__ import annotations
import re


def find_matches(text: str, query: str, case: bool = False, whole: bool = False, regex: bool = False):
    if not query:
        return []
    flags = 0 if case else re.IGNORECASE
    pat = query if regex else re.escape(query)
    if whole:
        pat = rf"\b{pat}\b"
    return list(re.finditer(pat, text, flags=flags))
