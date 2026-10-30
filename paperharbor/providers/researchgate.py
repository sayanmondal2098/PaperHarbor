"""ResearchGate publication links supplied by the user or bibliographic indexes.

No search scraping or guessed download endpoints: full texts must be advertised
by the publication page, or supplied as a verified file URL.
"""

import re
from urllib.parse import urljoin, urlsplit

from paperharbor.models import CandidatePDF
from paperharbor.providers.base import BaseProvider


def is_researchgate_url(url):
    parsed = urlsplit(url or "")
    host = (parsed.hostname or "").lower()
    return parsed.scheme in ("http", "https") and (host == "researchgate.net" or host.endswith(".researchgate.net"))


def publication_id(url):
    match = re.search(r"/publication/(\d+)(?:[_/]|$)", urlsplit(url).path)
    return match.group(1) if match else None


def researchgate_pdf_links(soup, page_url):
    """Extract advertised files for this publication, excluding cited/related work."""
    links = []
    current_id = publication_id(page_url)

    def add(raw):
        target = urljoin(page_url, raw)
        if not is_researchgate_url(target):
            return
        target_id = publication_id(target)
        if current_id and target_id and target_id != current_id:
            return
        if target not in links:
            links.append(target)

    for meta in soup.find_all("meta", attrs={"name": re.compile(r"^citation_pdf_url$", re.I)}):
        if meta.get("content"):
            add(meta["content"])
    for anchor in soup.find_all("a", href=True):
        if any(re.search(r"references|citations|related|recommend|supplement",
                str(parent.get("id", "")) + " " + " ".join(parent.get("class", [])), re.I)
               for parent in anchor.parents if getattr(parent, "attrs", None)):
            continue
        target = urljoin(page_url, anchor["href"])
        text = anchor.get_text(" ", strip=True).lower().replace("-", " ")
        # Article pages often link the same publication under a /profile/... URL.
        # Requiring a matching publication ID avoids grabbing unrelated PDFs.
        same_work = current_id and publication_id(target) == current_id
        if same_work and (re.search(r"\.pdf(?:$|\?)", target, re.I)
                          or ("/links/" in urlsplit(target).path and "download full text" in text)):
            add(anchor["href"])
    return links[:12]


class ResearchGateProvider(BaseProvider):
    @property
    def name(self):
        return "ResearchGate"

    def search(self, reference):
        candidates = []
        for url in dict.fromkeys([reference.url, reference.publisher_url]):
            if not is_researchgate_url(url) or not publication_id(url):
                continue
            direct = bool(re.search(r"\.pdf(?:$|\?)", url, re.I))
            candidates.append(CandidatePDF(url=url, provider=self.name,
                landing_page=url, is_direct_pdf=direct))
        return candidates
