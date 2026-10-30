"""Resolve direct PDF links from open-access landing pages."""

import logging
import re
from typing import List
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

WILEY_HOST = re.compile(r"(^|\.)onlinelibrary\.wiley\.com$")


def publisher_pdf_variants(url: str) -> List[str]:
    """Known direct-PDF URL forms for viewer/landing URLs (e.g. Wiley /epdf/ -> /pdfdirect/)."""
    parsed = urlparse(url)
    variants: List[str] = []
    if WILEY_HOST.search(parsed.netloc):
        m = re.search(r"/doi/(?:epdf|pdf|pdfdirect|full|abs)?/?(10\.\d{4,9}/.+?)(?:\?|$)", parsed.path + "?")
        if m:
            base = f"{parsed.scheme}://{parsed.netloc}/doi"
            doi = m.group(1)
            variants += [f"{base}/pdfdirect/{doi}?download=true", f"{base}/pdf/{doi}"]
    return variants


class LandingPageResolver:
    """Fetches a landing page and extracts PDF links (citation_pdf_url meta tag, .pdf anchors)."""

    def __init__(self, session: requests.Session, timeout: int = 20):
        self.session = session
        self.timeout = timeout

    def resolve(self, landing_url: str) -> List[str]:
        urls: List[str] = publisher_pdf_variants(landing_url)
        try:
            resp = self.session.get(landing_url, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException as e:
            logger.debug(f"[Landing] {landing_url}: {e}")
            return urls
        if resp.status_code != 200 or "html" not in resp.headers.get("content-type", "").lower():
            urls += publisher_pdf_variants(resp.url)
            return _dedupe(urls)

        soup = BeautifulSoup(resp.text, "html.parser")
        for meta in soup.find_all("meta", attrs={"name": re.compile(r"^citation_pdf_url$", re.I)}):
            if meta.get("content"):
                urls.append(urljoin(resp.url, meta["content"]))
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(" ", strip=True).lower()
            if re.search(r"\.pdf($|\?)", href, re.I) or "download pdf" in text or "full text pdf" in text:
                urls.append(urljoin(resp.url, href))
        urls += publisher_pdf_variants(resp.url)
        return _dedupe(urls)[:6]


def _dedupe(urls: List[str]) -> List[str]:
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out
