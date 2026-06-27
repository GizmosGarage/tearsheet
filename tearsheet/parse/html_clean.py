"""HTML -> normalized plain text."""

from __future__ import annotations

from bs4 import BeautifulSoup


def html_to_plain_text(html: str) -> str:
    """Convert filing HTML to normalized plain text."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup(["script", "style"]):
        script.extract()
    
    text = soup.get_text(separator=' ')
    import re
    text = re.sub(r'\s+', ' ', text).strip()
    text = text.replace(' .', '.')
    return text
