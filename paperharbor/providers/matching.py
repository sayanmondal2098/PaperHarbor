"""Conservative work matching and DOI extraction shared by discovery providers."""

import re
import unicodedata
from urllib.parse import unquote, urlsplit


def doi_from_url(url):
    parsed = urlsplit(url or "")
    host = (parsed.hostname or "").lower()
    if host not in ("doi.org", "dx.doi.org", "dl.acm.org", "www.dl.acm.org"):
        return None
    match = re.search(r"(10\.\d{4,9}/.+)", unquote(parsed.path), re.I)
    return match.group(1).rstrip("/").lower() if match else None


def same_title(expected, actual):
    def words(value):
        value = unicodedata.normalize("NFKD", value).casefold()
        value = re.sub(r"\\(?:[a-zA-Z]+)", " ", value)
        return re.findall(r"[a-z0-9]+", value)
    left, right = words(expected), words(actual)
    if not left or not right:
        return False
    # Exact normalized token order tolerates punctuation, hyphens, and line wrapping.
    if left == right:
        return True
    a, b = set(left), set(right)
    return len(left) >= 6 and len(right) >= 6 and len(a & b) / len(a | b) >= 0.94


def conflicts_with_doi(reference, url):
    found = doi_from_url(url)
    return bool(reference.clean_doi and found and found != reference.clean_doi.lower())
