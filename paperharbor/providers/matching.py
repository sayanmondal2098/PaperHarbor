"""Conservative work matching and DOI extraction shared by discovery providers."""

import re
import unicodedata
from urllib.parse import unquote, urlsplit


def doi_from_url(url):
    parsed = urlsplit(url or "")
    host = (parsed.hostname or "").lower()
    if host not in ("doi.org", "www.doi.org", "dx.doi.org", "doi.acm.org", "dl.acm.org", "www.dl.acm.org", "portal.acm.org"):
        return None
    match = re.search(r"(10\.\d{4,9}/.+)", unquote(parsed.path), re.I)
    return match.group(1).rstrip("/").lower() if match else None


def normalize_identifier(value):
    """Return (DOI, source URL) for a bare DOI or an HTTP(S) article URL."""
    value = (value or "").strip()
    if re.match(r"^doi:\s*", value, re.I):
        value = re.sub(r"^doi:\s*", "", value, flags=re.I)
    if re.fullmatch(r"10\.\d{4,9}/[^\s?#]+", value, re.I):
        return value.lower(), None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username and not parsed.password:
            return doi_from_url(value), value
    except ValueError:
        pass
    raise ValueError("Enter a DOI such as 10.1145/1557019.1557153 or an HTTP(S) article URL.")


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
