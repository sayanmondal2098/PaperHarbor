"""Reviewed author/conference copies missed by metadata indexes.

Entries are keyed by exact DOI and carry a public evidence page. This small
catalog supplements live discovery; it is not an exhaustive ACM mirror.
"""

import json
from functools import lru_cache
from pathlib import Path

from paperharbor.models import CandidatePDF
from paperharbor.providers.base import BaseProvider
from paperharbor.providers.matching import doi_from_url, same_title


@lru_cache(maxsize=1)
def source_catalog():
    path = Path(__file__).with_name("author_copies.json")
    return json.loads(path.read_text(encoding="utf-8"))


def author_copy_candidates(reference):
    doi = reference.clean_doi or doi_from_url(reference.url)
    record = source_catalog().get(doi.lower()) if doi else None
    if not record:
        return []
    # Some metadata indexes store only the main title before the subtitle.
    titles = (record["title"], record["title"].split(":")[0])
    if reference.title and not any(same_title(reference.title, title) for title in titles):
        return []
    return [
        CandidatePDF(url=url, provider="Verified author copies",
                     landing_page=record["source_page"], oa_status="green")
        for url in record["pdf_urls"]
    ]


class AuthorCopiesProvider(BaseProvider):
    @property
    def name(self):
        return "Verified author copies"

    def search(self, reference):
        return author_copy_candidates(reference)
