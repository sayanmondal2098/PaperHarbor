"""Discover public article copies from live web search, without a DOI catalog."""

import os
import re
import time
from urllib.parse import parse_qs, urlsplit, urljoin

import requests
from bs4 import BeautifulSoup

from paperharbor.local_files import normalized_text
from paperharbor.models import CandidatePDF
from paperharbor.providers.base import BaseProvider
from paperharbor.providers.matching import conflicts_with_doi


SEARCH_URL = "https://html.duckduckgo.com/html/"


def result_url(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urlsplit(urljoin(SEARCH_URL, value))
        if parsed.hostname in ("duckduckgo.com", "html.duckduckgo.com"):
            value = parse_qs(parsed.query).get("uddg", [""])[0]
            parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password
                or parsed.hostname in ("duckduckgo.com", "html.duckduckgo.com", "serpapi.com")):
            return None
        return parsed.geturl()
    except ValueError:
        return None


class WebSearchProvider(BaseProvider):
    """Search title + filetype:pdf and verify downloaded content before saving."""

    def __init__(self, email=None, session=None):
        super().__init__(email=email, session=session)
        self._cache = {}
        self._next_request = 0.0
        self._blocked = ""

    @property
    def name(self):
        return "Live web search"

    def search(self, reference):
        self.last_error = ""
        title = normalized_text(reference.title)
        # DOI-only web hits can refer to papers citing the target. Require a
        # meaningful title, then inspect the actual PDF's first page as well.
        if len(title.split()) < 4:
            return []
        key = (title, (reference.clean_doi or "").casefold())
        if key in self._cache:
            candidates, self.last_error = self._cache[key]
            return list(candidates)
        if self._blocked:
            self.last_error = self._blocked
            return []
        wait = self._next_request - time.monotonic()
        if wait > 0:
            time.sleep(min(wait, 5))
        api_key = os.environ.get("SERPAPI_API_KEY", "").strip()
        query = '"' + reference.title.strip() + '" filetype:pdf'
        try:
            if api_key:
                response = self.session.get("https://serpapi.com/search.json", params={
                    "engine": "google", "q": query, "num": 10, "api_key": api_key},
                    timeout=(10, 20), allow_redirects=False)
            else:
                response = self.session.get(SEARCH_URL, params={"q": query}, timeout=(10, 20),
                    headers={"Accept": "text/html,application/xhtml+xml"})
            if response.status_code != 200:
                self.last_error = f"HTTP {response.status_code} from live web search"
                if response.status_code in (202, 401, 402, 403, 429):
                    self._blocked = self.last_error + "; further web searches stopped for this job"
                return []
            if api_key:
                data = response.json()
                if not isinstance(data, dict) or data.get("error"):
                    self._blocked = self.last_error = "Web search API error; check credentials and quota"
                    return []
                results = data.get("organic_results", [])
            else:
                soup = BeautifulSoup(response.text, "html.parser")
                if soup.select_one('#challenge-form, #anomaly-modal, .anomaly-modal'):
                    self._blocked = self.last_error = "Web search access challenge; further searches stopped for this job"
                    return []
                results = []
                for row in soup.select(".result")[:10]:
                    anchor = row.select_one(".result__a[href]")
                    snippet = row.select_one(".result__snippet")
                    if anchor:
                        results.append({"title": anchor.get_text(" ", strip=True), "link": anchor["href"],
                                        "snippet": snippet.get_text(" ", strip=True) if snippet else ""})
                if not results and not soup.select_one('.no-results, .results'):
                    self.last_error = "Unrecognized web search response; no links accepted"
                    return []
            if not isinstance(results, list):
                raise ValueError("Invalid results")
            candidates, seen = [], set()
            for result in results[:10]:
                if not isinstance(result, dict):
                    continue
                url = result_url(result.get("link"))
                text = normalized_text(str(result.get("title", "")) + " " + str(result.get("snippet", "")))
                if not url or url in seen or title not in text or conflicts_with_doi(reference, url):
                    continue
                if re.search(r"citation[-_]report", urlsplit(url).path, re.I):
                    continue
                seen.add(url)
                direct = bool(re.search(r"\.pdf$|/bitstreams?/.*(?:download|content)$", urlsplit(url).path, re.I))
                candidates.append(CandidatePDF(url=url, provider=self.name, landing_page=url,
                    is_direct_pdf=direct, requires_identity_check=True))
            candidates.sort(key=lambda candidate: not candidate.is_direct_pdf)
            if not candidates:
                self.last_error = "No matching public PDF or repository link in live web search"
            self._cache[key] = (candidates, self.last_error)
            return list(candidates)
        except (requests.RequestException, ValueError):
            self.last_error = "Live web search failed or returned invalid data"
            return []
        finally:
            self._next_request = time.monotonic() + 5
