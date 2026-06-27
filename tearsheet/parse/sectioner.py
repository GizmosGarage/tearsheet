"""Split a 10-K into Items (1, 1A, 7, ...)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Section:
    """A single 10-K item section."""

    item: str
    title: str
    text: str


def split_10k_sections(plain_text: str) -> list[Section]:
    """Split normalized 10-K plain text into item sections."""
    raise NotImplementedError
