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
        r"^[ \t]*(?:PART[ \t]+[IVX]+[ \t]+)?ITEM[ \t]*([0-9]+[ \t]*[A-Z]?)([\.\:\-\u2013\u2014]|[ \t]+)[ \t]*([^\n]*)$", 
        re.IGNORECASE | re.MULTILINE
    )
    matches = list(pattern.finditer(plain_text))
    
    ITEM_ORDER = {
        "1": 1, "1A": 2, "1B": 3, "1C": 4, "2": 5, "3": 6, "4": 7, "5": 8, 
        "6": 9, "7": 10, "7A": 11, "8": 12, "9": 13, "9A": 14, "9B": 15, 
        "10": 16, "11": 17, "12": 18, "13": 19, "14": 20, "15": 21
    }
    
    valid_matches = []
    for match in matches:
        item = match.group(1).upper().replace(" ", "")
        delim = match.group(2)
        title = match.group(3).strip()
        
        if delim.strip() == "" and title:
            item_prefixes = {
                "1": ["BUSINESS"], "1A": ["RISK"], "1B": ["UNRESOLVED"], "1C": ["CYBERSECURITY"],
                "2": ["PROPERTIES"], "3": ["LEGAL"], "4": ["MINE"], "5": ["MARKET"], "6": ["SELECTED"],
                "7": ["MANAGEMENT"], "7A": ["QUANTITATIVE"], "8": ["FINANCIAL"], "9": ["CHANGES"],
                "9A": ["CONTROLS"], "9B": ["OTHER"], "10": ["DIRECTORS"], "11": ["EXECUTIVE"],
                "12": ["SECURITY"], "13": ["CERTAIN"], "14": ["PRINCIPAL"], "15": ["EXHIBITS"]
            }
            allowed = item_prefixes.get(item, [])
            if not any(title.upper().startswith(p) for p in allowed):
                continue
                
        if re.search(r'\.{4,}', title):
            continue
            
        valid_matches.append((match, item, title))
        
    sequences = []
    current_seq = []
    max_idx = -1
    
    for m in valid_matches:
        idx = ITEM_ORDER.get(m[1], -1)
        if idx <= max_idx and idx != -1:
            sequences.append(current_seq)
            current_seq = []
            max_idx = -1
        current_seq.append(m)
        if idx != -1:
            max_idx = idx
            
    if current_seq:
        sequences.append(current_seq)
        
    valid_seqs = []
    for seq in sequences:
        if not seq:
            continue
        is_valid = True
        for i in range(len(seq) - 1):
            idx1 = ITEM_ORDER.get(seq[i][1], -1)
            idx2 = ITEM_ORDER.get(seq[i+1][1], -1)
            # Check for jumps or out of order
            if idx2 != idx1 + 1:
                is_valid = False
                break
        if is_valid:
            valid_seqs.append(seq)
            
    best_seq = []
    best_span = -1
    
    # Select the one with the largest raw text span from validated monotonic sequences
    for i, seq in enumerate(valid_seqs):
        start_char = seq[0][0].start()
        # Find where this sequence ends
        # It ends where the NEXT sequence in the ORIGINAL sequences list begins, or EOF.
        # To be simple and robust, we can just say it ends at the last match's start + some text, 
        # or just find the index of this seq in sequences.
        orig_idx = sequences.index(seq)
        end_char = sequences[orig_idx+1][0][0].start() if orig_idx + 1 < len(sequences) and sequences[orig_idx+1] else len(plain_text)
        
        span = end_char - start_char
        if span > best_span:
            best_span = span
            best_seq = seq
            
    for i, (match, item, title) in enumerate(best_seq):
        start_idx = match.end()
        end_idx = best_seq[i+1][0].start() if i + 1 < len(best_seq) else len(plain_text)
        text = plain_text[start_idx:end_idx].strip()
        sections.append(Section(item=item, title=title, text=text))
        
    return sections
