"""Resolve direct PDF links from open-access landing pages."""

import logging
import re
from typing import List
from urllib.parse import urljoin, urlparse, parse_qs, unquote
from paperharbor.providers.matching import doi_from_url

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

WILEY_HOST = re.compile(r"(^|\.)onlinelibrary\.wiley\.com$")
# Publishers whose content is fully open access; a blocked download here is still legal to fetch by hand
OA_HOSTS = re.compile(r"(^|\.)(dl\.acm\.org|mdpi\.com|mdpi-res\.com|frontiersin\.org|plos\.org|biomedcentral\.com|usenix\.org|arxiv\.org|pmc\.ncbi\.nlm\.nih\.gov|openreview\.net|eprint\.iacr\.org)$")


def is_known_oa_host(url: str) -> bool:
    return bool(OA_HOSTS.search((urlparse(url or "").hostname or "").lower()))


def publisher_pdf_variants(url: str) -> List[str]:
    """Known direct-PDF URL forms for viewer/landing URLs (Wiley, MDPI, Frontiers, ...)."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path + (";" + parsed.params if parsed.params else "")
    variants: List[str] = []
    if WILEY_HOST.search(host):
        m = re.search(r"/doi/(?:epdf|pdf|pdfdirect|full|abs)?/?(10\.\d{4,9}/.+?)(?:\?|$)", path + "?")
        if m:
            base = f"{parsed.scheme}://{parsed.netloc}/doi"
            doi = m.group(1)
            variants += [f"{base}/pdfdirect/{doi}?download=true", f"{base}/pdf/{doi}"]
    elif (host == "mdpi.com" or host.endswith(".mdpi.com")) and re.search(r"/\d{4}-\d{3}[\dXx]/|/\d+/\d+/\d+", parsed.path):
        path = parsed.path.rstrip("/")
        if not path.endswith("/pdf"):
            variants.append(f"{parsed.scheme}://{parsed.netloc}{path}/pdf")
    elif (host == "frontiersin.org" or host.endswith(".frontiersin.org")) and "/articles/" in parsed.path:
        path = re.sub(r"/(full|abstract|pdf)$", "", parsed.path.rstrip("/"))
        variants.append(f"{parsed.scheme}://{parsed.netloc}{path}/pdf")
    elif host in ("link.springer.com", "link.springernature.com"):
        match = re.search(r"/(?:article|content/pdf)/(10\..+?)(?:\.pdf)?$", parsed.path)
        if match:
            variants.append(f"https://link.springer.com/content/pdf/{match.group(1)}.pdf")
    elif host in ("dl.acm.org", "www.dl.acm.org"):
        match = re.search(r"/doi/(?:abs/|full/|fullHtml/|epdf/|pdf/)?(10\.[^\s]+)", unquote(parsed.path), re.I)
        if match:
            variants.append(f"https://dl.acm.org/doi/pdf/{match.group(1)}")
    elif host in ("arxiv.org", "www.arxiv.org"):
        match = re.search(r"/(?:abs|pdf)/(.+?)(?:\.pdf)?$", parsed.path)
        if match:
            variants.append(f"https://arxiv.org/pdf/{match.group(1)}")
    elif host in ("openreview.net", "www.openreview.net") and parsed.path == "/forum":
        note_id = parse_qs(parsed.query).get("id", [""])[0]
        if note_id:
            from urllib.parse import urlencode
            variants.append("https://openreview.net/pdf?" + urlencode({"id": note_id}))
    elif host == "eprint.iacr.org":
        match = re.fullmatch(r"/(\d{4}/\d+)(?:\.pdf)?/?", parsed.path)
        if match:
            variants.append(f"https://eprint.iacr.org/{match.group(1)}.pdf")
    elif host == "ieeexplore.ieee.org":
        number = parse_qs(parsed.query).get("arnumber", [""])[0]
        if not number:
            match = re.search(r"/(?:abstract/)?document/(\d+)", parsed.path)
            number = match.group(1) if match else ""
        if number.isdigit():
            variants.append(f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={number}")
    elif host == "hal.science" or host.endswith(".hal.science"):
        match = re.fullmatch(r"/((?:hal|inria|tel|pastel)-\d+(?:v\d+)?)(?:/document)?/?", parsed.path)
        if match:
            variants.append(f"https://{host}/{match.group(1)}/document")
    return variants


class LandingPageResolver:
    """Fetches a landing page and extracts PDF links (citation_pdf_url meta tag, .pdf anchors)."""

    def __init__(self, session: requests.Session, timeout: int = 20):
        # Own session: landing pages must be fetched as HTML, not with the PDF-first Accept header
        self.session = requests.Session()
        self.session.cookies = session.cookies
        self.session.headers.update({
            "User-Agent": session.headers.get("User-Agent", ""),
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.timeout = timeout
        self.last_error = ""

    def resolve(self, landing_url: str, expected_doi=None) -> List[str]:
        self.last_error = ""
        urls: List[str] = publisher_pdf_variants(landing_url)
        try:
            resp = self.session.get(landing_url, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException as e:
            self.last_error = f"{type(e).__name__}: {e}"
            logger.debug(f"[Landing] {landing_url}: {e}")
            return urls
        if resp.status_code != 200:
            self.last_error = f"HTTP {resp.status_code} while resolving article page"
            urls += publisher_pdf_variants(resp.url)
            return _dedupe(urls)
        if "html" not in resp.headers.get("content-type", "").lower():
            # The URL may itself be a PDF (e.g. a direct report link): let the downloader validate it
            urls.append(landing_url)
            urls += publisher_pdf_variants(resp.url)
            return _dedupe(urls)

        soup = BeautifulSoup(resp.text, "html.parser")
        resolved_doi = doi_from_url(resp.url)
        if expected_doi and resolved_doi and resolved_doi != expected_doi.lower():
            self.last_error = f"Rejected redirect with conflicting DOI {resolved_doi}"
            return []
        if urlparse(resp.url).hostname in ("arxiv.org", "www.arxiv.org", "export.arxiv.org"):
            notice = soup.find(string=re.compile(r"this paper has been withdrawn", re.I))
            if notice:
                comments = soup.select_one(".comments")
                reason = comments.get_text(" ", strip=True) if comments else ""
                self.last_error = "Withdrawn arXiv record: " + str(notice).strip() + (". " + reason if reason else "")
                return []
        for meta in soup.find_all("meta", attrs={"name": re.compile(r"^citation_doi$", re.I)}):
            found = (meta.get("content") or "").strip()
            found = doi_from_url(found) or found.lower()
            if expected_doi and found and found != expected_doi.lower():
                self.last_error = f"Rejected page with conflicting DOI {found}"
                return []
        for meta in soup.find_all("meta", attrs={"name": re.compile(r"^(citation_pdf_url|wkhealth_pdf_url|eprints.document_url)$", re.I)}):
            if meta.get("content"):
                urls.append(urljoin(resp.url, meta["content"]))
        # Authoritative article metadata takes precedence over PDFs cited in its references.
        if len(urls) > len(publisher_pdf_variants(landing_url)):
            return _dedupe(urls + publisher_pdf_variants(resp.url))[:12]
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(" ", strip=True).lower()
            in_references = any(re.search(r"references|reference-list|ref-list|bibliography|related|supplement",
                str(parent.get("id", "")) + " " + " ".join(parent.get("class", [])), re.I)
                for parent in a.parents if getattr(parent, "attrs", None))
            if in_references:
                continue
            target = urljoin(resp.url, href)
            same_host = urlparse(target).hostname == urlparse(resp.url).hostname
            pdf_link = bool(re.search(r"\.pdf($|\?)", href, re.I))
            pdf_control = "download pdf" in text or "full text pdf" in text or "view pdf" in text
            # ORBilu and other repositories often label a file simply "Download".
            download_control = text == "download" and re.search(r"\.pdf($|\?)|/bitstream/|/bitstreams/", target, re.I)
            repository_file = same_host and ("/bitstreams/" in href or "/bitstream/" in href) and ("download" in text or ".pdf" in text)
            if (same_host and pdf_link) or pdf_control or repository_file or download_control:
                urls.append(target)
        for embedded in soup.find_all(["iframe", "embed", "object"]):
            raw_target = embedded.get("src") or embedded.get("data") or ""
            # PDF.js uses viewer.html?file=<actual PDF>.
            file_target = parse_qs(urlparse(raw_target).query).get("file", [""])[0]
            target = urljoin(resp.url, file_target or raw_target)
            if urlparse(target).hostname == urlparse(resp.url).hostname and (re.search(r"\.pdf($|\?)", target, re.I) or "/stampPDF/getPDF.jsp" in target):
                urls.append(target)
        urls += publisher_pdf_variants(resp.url)
        if not urls:
            self.last_error = "Article page contained no identifiable PDF download link"
        return _dedupe(urls)[:12]


def _dedupe(urls: List[str]) -> List[str]:
    seen, out = set(), []
    for u in urls:
        if urlparse(u).scheme in ("http", "https") and u not in seen:
            seen.add(u)
            out.append(u)
    return out
