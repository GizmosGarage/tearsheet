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
        r"^[ \t]*(?:PART[ \t]+[IVX]+[ \t]+)?ITEM[ \t]*([0-9]+[ \t]*[A-Z]?)(?:[\.\:]|[ \t]+)[ \t]*([^\n]*)$", 
        re.IGNORECASE | re.MULTILINE
    )
    matches = list(pattern.finditer(plain_text))
    
    # Pre-filter TOC by checking distance to next match
    real_matches = []
    for i, match in enumerate(matches):
        start_idx = match.end()
        end_idx = matches[i+1].start() if i + 1 < len(matches) else len(plain_text)
        text_between = plain_text[start_idx:end_idx].strip()
        if len(text_between) < 15 and not any(w in text_between.lower() for w in ["none", "not applicable", "omitted"]):
            continue
        real_matches.append(match)
        
    ITEM_ORDER = {
        "1": 1, "1A": 2, "1B": 3, "1C": 4, "2": 5, "3": 6, "4": 7, "5": 8, 
        "6": 9, "7": 10, "7A": 11, "8": 12, "9": 13, "9A": 14, "9B": 15, 
        "10": 16, "11": 17, "12": 18, "13": 19, "14": 20, "15": 21
    }
    
    valid_matches = []
    max_item_idx = -1
    
    for match in real_matches:
        item = match.group(1).upper().replace(" ", "")
        idx = ITEM_ORDER.get(item, -1)
        if idx != -1:
            if idx <= max_item_idx:
                continue
            max_item_idx = idx
            
        title = match.group(2).strip()
        if re.search(r'\.{4,}', title):
            continue
        valid_matches.append((match, title))
        
    for i, (match, title) in enumerate(valid_matches):
        item = match.group(1).upper().replace(" ", "")
        
        start_idx = match.end()
        # Find where the next valid match starts, or EOF
        # We must look at valid_matches[i+1]
        end_idx = valid_matches[i+1][0].start() if i + 1 < len(valid_matches) else len(plain_text)
        
        text = plain_text[start_idx:end_idx].strip()
        sections.append(Section(item=item, title=title, text=text))
        
    return sections
