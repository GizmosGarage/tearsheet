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
    
    pattern = re.compile(
        r"^\s*(?:PART\s+[IVX]+\s+)?ITEM\s+([0-9]+\s*[A-Z]?)(?:[\.\:]|\s+)\s*(.*)$", 
        re.IGNORECASE | re.MULTILINE
    )
    matches = list(pattern.finditer(plain_text))
    
    valid_matches = []
    for match in matches:
        title = match.group(2).strip()
        if re.search(r'\.{4,}', title) or re.search(r'\s\d+$', title):
            continue
        valid_matches.append((match, title))
        
    for i, (match, title) in enumerate(valid_matches):
        item = match.group(1).upper().replace(" ", "")
        
        start_idx = match.end()
        end_idx = valid_matches[i+1][0].start() if i + 1 < len(valid_matches) else len(plain_text)
        
        text = plain_text[start_idx:end_idx].strip()
        sections.append(Section(item=item, title=title, text=text))
        
    return sections
