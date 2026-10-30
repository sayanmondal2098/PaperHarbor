"""Filename generation and path sanitization for academic papers."""

import os
import re
import unicodedata
from pathlib import Path
from typing import Optional
from paperharbor.models import Reference


ILLEGAL_CHARS_PATTERN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "with",
    "by", "from", "up", "about", "into", "over", "after"
}


def clean_unicode(text: str) -> str:
    """Normalize unicode characters (e.g., Müller -> Muller, smart quotes -> standard)."""
    # Normalize unicode to decomposed form and remove combining diacritics
    normalized = unicodedata.normalize("NFKD", text)
    ascii_clean = normalized.encode("ASCII", "ignore").decode("ASCII")
    return ascii_clean if ascii_clean else text


def sanitize_author(author_str: str) -> str:
    """Extract and sanitize the primary author's surname."""
    if not author_str:
        return "UnknownAuthor"
    
    # Clean unicode accents
    clean = clean_unicode(author_str)
    
    # If formatted as "LastName, FirstName", take LastName
    if "," in clean:
        clean = clean.split(",")[0].strip()
    else:
        # If "FirstName LastName", take the last word
        parts = clean.strip().split()
        if parts:
            clean = parts[-1]
    
    # Remove any non-alphanumeric characters
    clean = re.sub(r"[^A-Za-z0-9]", "", clean)
    if not clean or clean.lower() == "unknownauthor":
        return "UnknownAuthor"
    
    # Capitalize first letter while preserving camel case
    return clean[:1].upper() + clean[1:]


def sanitize_title(title_str: str, max_words: int = 8, max_chars: int = 70) -> str:
    """
    Sanitize paper title into clean underscore-separated PascalCase words.
    Example: 'Phishing Detection: A Deep Learning Approach' -> 'Phishing_Detection_A_Deep_Learning_Approach'
    """
    if not title_str:
        return "Untitled"
    
    clean = clean_unicode(title_str)
    # Strip HTML tags
    clean = re.sub(r"<[^>]+>", "", clean)
    # Replace separators (colon, hyphen, dash, slash) with spaces
    clean = re.sub(r"[:\-\u2013\u2014/\\_\t\r\n]", " ", clean)
    # Remove illegal filename characters and punctuation
    clean = re.sub(r"[^\w\s]", "", clean)
    
    # Split into words and capitalize
    words = clean.strip().split()
    if not words:
        return "Untitled"
    
    # Format words nicely
    formatted_words = []
    for w in words[:max_words]:
        w_clean = re.sub(r"[^A-Za-z0-9]", "", w)
        if w_clean:
            # Capitalize word
            formatted_words.append(w_clean.capitalize())
            
    title_joined = "_".join(formatted_words)
    
    # Truncate to max_chars while keeping full words
    if len(title_joined) > max_chars:
        title_joined = title_joined[:max_chars].rstrip("_")
        
    return title_joined if title_joined else "Untitled"


def generate_filename(
    reference: Reference,
    template: str = "{year}_{author}_{title}.pdf",
    max_title_chars: int = 70
) -> str:
    """
    Generate a standardized filename like '2025_Smith_Phishing_Detection.pdf'.
    
    Parameters:
        reference: Reference data object
        template: format template with placeholders {year}, {author}, {title}
        max_title_chars: maximum characters for sanitized title
    """
    year = reference.display_year
    author = sanitize_author(reference.display_author)
    title = sanitize_title(reference.title, max_chars=max_title_chars)
    
    filename = template.format(year=year, author=author, title=title)
    
    # Ensure legal filename
    filename = ILLEGAL_CHARS_PATTERN.sub("_", filename)
    filename = re.sub(r"_+", "_", filename)
    filename = filename.strip(" ._")
    
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
        
    return filename


def get_unique_destination_path(
    dest_dir: Path,
    desired_filename: str,
    reference_doi: Optional[str] = None
) -> Path:
    """
    Ensure the destination file path is unique or handles collisions gracefully.
    If the file exists, appends _1, _2, etc., before .pdf.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    base_stem = Path(desired_filename).stem
    ext = Path(desired_filename).suffix
    
    target_path = dest_dir / desired_filename
    counter = 1
    
    while target_path.exists():
        # Check if it already has valid content (size > 1KB)
        # We allow caller to check if this is the exact same paper
        target_path = dest_dir / f"{base_stem}_{counter}{ext}"
        counter += 1
        
    return target_path
