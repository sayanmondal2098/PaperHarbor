"""Resolve direct PDF links from open-access landing pages."""

import logging
import re
from typing import List
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

WILEY_HOST = re.compile(r"(^|\.)onlinelibrary\.wiley\.com$")
# Publishers whose content is fully open access; a blocked download here is still legal to fetch by hand
OA_HOSTS = re.compile(r"(^|\.)(mdpi\.com|frontiersin\.org|plos\.org|biomedcentral\.com|usenix\.org|arxiv\.org)$")


def is_known_oa_host(url: str) -> bool:
    return bool(OA_HOSTS.search(urlparse(url or "").netloc.lower()))


def publisher_pdf_variants(url: str) -> List[str]:
    """Known direct-PDF URL forms for viewer/landing URLs (Wiley, MDPI, Frontiers, ...)."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    variants: List[str] = []
    if WILEY_HOST.search(host):
        m = re.search(r"/doi/(?:epdf|pdf|pdfdirect|full|abs)?/?(10\.\d{4,9}/.+?)(?:\?|$)", parsed.path + "?")
        if m:
            base = f"{parsed.scheme}://{parsed.netloc}/doi"
            doi = m.group(1)
            variants += [f"{base}/pdfdirect/{doi}?download=true", f"{base}/pdf/{doi}"]
    elif host.endswith("mdpi.com") and re.search(r"/\d{4}-\d{3}[\dXx]/|/\d+/\d+/\d+", parsed.path):
        path = parsed.path.rstrip("/")
        if not path.endswith("/pdf"):
            variants.append(f"{parsed.scheme}://{parsed.netloc}{path}/pdf")
    elif host.endswith("frontiersin.org") and "/articles/" in parsed.path:
        path = re.sub(r"/(full|abstract|pdf)$", "", parsed.path.rstrip("/"))
        variants.append(f"{parsed.scheme}://{parsed.netloc}{path}/pdf")
    return variants


class LandingPageResolver:
    """Fetches a landing page and extracts PDF links (citation_pdf_url meta tag, .pdf anchors)."""

    def __init__(self, session: requests.Session, timeout: int = 20):
        # Own session: landing pages must be fetched as HTML, not with the PDF-first Accept header
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": session.headers.get("User-Agent", ""),
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.timeout = timeout

    def resolve(self, landing_url: str) -> List[str]:
        urls: List[str] = publisher_pdf_variants(landing_url)
        try:
            resp = self.session.get(landing_url, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException as e:
            logger.debug(f"[Landing] {landing_url}: {e}")
            return urls
        if resp.status_code != 200 or "html" not in resp.headers.get("content-type", "").lower():
            # The URL may itself be a PDF (e.g. a direct report link): let the downloader validate it
            urls.append(landing_url)
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
