"""Split a 10-K into Items (1, 1A, 7, ...)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Section:
    """A single 10-K item section."""

    item: str
    title: str
    text: str


import re

def split_10k_sections(plain_text: str) -> list[Section]:
    """Split normalized 10-K plain text into item sections."""
    sections = []
    
    pattern = re.compile(r"^\s*Item\s+([0-9]+[A-Z]?)\.\s+(.*)$", re.IGNORECASE | re.MULTILINE)
    matches = list(pattern.finditer(plain_text))
    
    for i, match in enumerate(matches):
        item = match.group(1).upper()
        title = match.group(2).strip()
        
        start_idx = match.end()
        end_idx = matches[i+1].start() if i + 1 < len(matches) else len(plain_text)
        
        text = plain_text[start_idx:end_idx].strip()
        sections.append(Section(item=item, title=title, text=text))
        
    return sections
