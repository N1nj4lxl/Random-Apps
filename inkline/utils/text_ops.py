from __future__ import annotations
import json
import re


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def reading_time_minutes(text: str) -> int:
    return max(1, word_count(text) // 200) if text.strip() else 0


def remove_double_spaces(text: str) -> str:
    return re.sub(r" {2,}", " ", text)


def trim_empty_lines(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join([ln for ln in lines if ln])


def format_json(text: str) -> str:
    return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
