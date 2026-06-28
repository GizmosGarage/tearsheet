"""HTML -> normalized plain text."""

from __future__ import annotations

from bs4 import BeautifulSoup


def html_to_plain_text(html: str) -> str:
    """Convert filing HTML to normalized plain text."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup(["script", "style"]):
        script.extract()
    
    for block in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "li", "br"]):
        block.insert_after("\n")
        
    text = soup.get_text()
    
    lines = []
    for line in text.split("\n"):
        line = " ".join(line.split())
        if line:
            lines.append(line)
            
    return "\n".join(lines).replace(" .", ".")
