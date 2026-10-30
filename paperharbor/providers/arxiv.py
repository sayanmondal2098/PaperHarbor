"""arXiv open access repository provider.

Detects arXiv preprints via DOI, arXiv IDs in metadata, or arXiv search API,
and produces direct download links to the PDF.
"""

import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import List, Optional
import requests

from paperharbor.models import CandidatePDF, Reference
from paperharbor.providers.base import BaseProvider
from paperharbor.providers.matching import same_title

logger = logging.getLogger(__name__)

ARXIV_ID_REGEX = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:\s*|10\.48550/arXiv\.)([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?|[a-z\-]+(?:\.[A-Z]{2})?/[0-9]{7})",
    re.IGNORECASE
)


class ArxivProvider(BaseProvider):
    """Provides direct full-text PDF links for papers hosted on arXiv."""

    @property
    def name(self) -> str:
        return "arXiv"

    def search(self, reference: Reference) -> List[CandidatePDF]:
        # 1. Check for arXiv ID in DOI, URL, or extra
        arxiv_id = self._extract_arxiv_id(reference)
        if arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            landing = f"https://arxiv.org/abs/{arxiv_id}"
            return [CandidatePDF(
                url=pdf_url,
                provider=self.name,
                landing_page=landing,
                oa_status="green",
                version="submittedVersion",
                is_direct_pdf=True
            )]

        # 2. Try arXiv API query by title if title is substantial
        if reference.title and len(reference.title.strip()) > 10:
            found_id = self._query_arxiv_api(reference.title)
            if found_id:
                return [CandidatePDF(
                    url=f"https://arxiv.org/pdf/{found_id}.pdf",
                    provider=self.name,
                    landing_page=f"https://arxiv.org/abs/{found_id}",
                    oa_status="green",
                    version="submittedVersion",
                    is_direct_pdf=True
                )]

        return []

    def _extract_arxiv_id(self, reference: Reference) -> Optional[str]:
        # Check DOI
        if reference.doi:
            match = ARXIV_ID_REGEX.search(reference.doi)
            if match:
                return match.group(1)

        # Check URL
        if reference.url:
            match = ARXIV_ID_REGEX.search(reference.url)
            if match:
                return match.group(1)

        # Check Extra
        if reference.extra:
            match = ARXIV_ID_REGEX.search(reference.extra)
            if match:
                return match.group(1)

        return None

    def _query_arxiv_api(self, title: str) -> Optional[str]:
        # Clean title of special symbols
        clean_title = re.sub(r"[^\w\s]", " ", title).strip()
        encoded = urllib.parse.quote(f'ti:"{clean_title}"')
        url = f"https://export.arxiv.org/api/query?search_query={encoded}&max_results=3"

        try:
            resp = self.get(url, timeout=12)
            if resp.status_code != 200:
                return None

            root = ET.fromstring(resp.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            for entry in root.findall("atom:entry", ns):
                entry_title = entry.find("atom:title", ns)
                if entry_title is not None and entry_title.text:
                    et_clean = re.sub(r"\s+", " ", entry_title.text.strip().lower())
                    ref_clean = re.sub(r"\s+", " ", title.strip().lower())

                    if same_title(ref_clean, et_clean):
                        id_elem = entry.find("atom:id", ns)
                        if id_elem is not None and id_elem.text:
                            match = ARXIV_ID_REGEX.search(id_elem.text)
                            if match:
                                return match.group(1)

            return None
        except Exception as e:
            logger.debug(f"[arXiv] API search error: {e}")
            return None
