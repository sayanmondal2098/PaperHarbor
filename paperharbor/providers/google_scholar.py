"""Bounded Google Scholar searches feeding the normal PDF download pipeline."""

import os
import re
import time
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from paperharbor.http_helpers import retry_after_seconds
from paperharbor.models import CandidatePDF
from paperharbor.providers.base import BaseProvider
from paperharbor.providers.matching import conflicts_with_doi, same_title


SCHOLAR_URL = "https://scholar.google.com/scholar"


def external_url(value):
    """Unwrap Scholar redirects, rejecting internal actions and non-web links."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urlsplit(urljoin(SCHOLAR_URL, value))
        if parsed.hostname == "scholar.google.com" and parsed.path in ("/scholar_url", "/url"):
            query = parse_qs(parsed.query)
            return external_url(query.get("url", query.get("q", [""]))[0]) if query else None
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.hostname == "scholar.google.com"
                or parsed.hostname.endswith(".google.com") or parsed.hostname == "google.com"):
            return None
        return parsed.geturl()
    except (ValueError, RecursionError):
        return None


class GoogleScholarProvider(BaseProvider):
    """Search once per reference; pause on blocks instead of retrying challenges.

    SERPAPI_API_KEY selects SerpApi's Google Scholar JSON endpoint. Otherwise
    parse the normal Scholar result page. No browser, login, or paid API is
    required for the direct mode, but Google may refuse automated requests.
    """

    def __init__(self, email=None, session=None):
        super().__init__(email=email, session=session)
        self._next_request = 0.0
        self._cache = {}
        self._blocked_reason = ""

    @property
    def name(self):
        return "Google Scholar"

    def search(self, reference):
        self.last_error = ""
        title = reference.title.strip()
        doi = reference.clean_doi
        if not doi and len(title) < 12:
            return []
        cache_key = (title.casefold(), (doi or "").casefold())
        if cache_key in self._cache:
            candidates, self.last_error = self._cache[cache_key]
            return list(candidates)
        if self._blocked_reason:
            self.last_error = self._blocked_reason
            return []
        remaining = self._cooldown_until - time.monotonic()
        if remaining > 0:
            self.last_error = f"HTTP 429: Scholar search paused; retry in {remaining:.0f}s"
            return []
        api_key = os.environ.get("SERPAPI_API_KEY", "").strip()
        # Independent Session prevents API credentials reaching a publisher or
        # another metadata service through the aggregator's shared Session.
        query = f'"{title}"' if title else doi
        wait = self._next_request - time.monotonic()
        if wait > 0:
            time.sleep(min(wait, 15))
        try:
            if api_key:
                response = self.session.get("https://serpapi.com/search.json", params={
                    "engine": "google_scholar", "q": query, "hl": "en", "num": 5,
                    "api_key": api_key}, timeout=(10, 20), allow_redirects=False)
            else:
                response = self.session.get(SCHOLAR_URL, params={"q": query, "hl": "en", "num": 5},
                    headers={"Accept": "text/html,application/xhtml+xml"}, timeout=(10, 20))
            if response.status_code == 429:
                delay = retry_after_seconds(response.headers.get("Retry-After"))
                self._cooldown_until = time.monotonic() + max(900, delay or 0)
                self.last_error = "HTTP 429: Scholar search rate limited; automated searches paused for at least 15 minutes"
                return []
            if response.status_code != 200:
                self.last_error = f"HTTP {response.status_code} from Scholar search" + (" API" if api_key else "")
                if response.status_code in (401, 402, 403):
                    self._blocked_reason = self.last_error + "; further Scholar requests stopped for this job"
                return []
            if api_key:
                data = response.json()
                if not isinstance(data, dict) or data.get("error"):
                    # API errors may contain the request URL/key. Never log them.
                    self.last_error = "Scholar search API returned an error; check API credentials and quota"
                    self._blocked_reason = self.last_error
                    return []
                results = data.get("organic_results", [])
            else:
                soup = BeautifulSoup(response.text, "html.parser")
                if ("/sorry/" in response.url or soup.select_one('#gs_captcha_f, #captcha-form, .g-recaptcha')
                        or re.search(r"unusual traffic|not a robot|automated queries", soup.get_text(" "), re.I)):
                    self.last_error = "Scholar access challenge detected; further automated Scholar searches stopped for this job"
                    self._blocked_reason = self.last_error
                    return []
                results = self._html_results(soup)
                if not results and not soup.select_one("#gs_res_ccl_mid, #gs_top"):
                    self.last_error = "Unrecognized Scholar response; no PDF links accepted"
                    return []
            candidates = self._candidates(results, reference)
            if not candidates:
                self.last_error = "No matching Scholar result with a public PDF or article link"
            self._cache[cache_key] = (candidates, self.last_error)
            return list(candidates)
        except (requests.RequestException, ValueError):
            # In particular, don't include a SerpApi URL containing the key.
            self.last_error = "Scholar search request failed or returned invalid data"
            return []
        finally:
            self._next_request = time.monotonic() + (1 if api_key else 15)

    def _html_results(self, soup):
        results = []
        for row in soup.select(".gs_r.gs_or.gs_scl")[:5]:
            heading = row.select_one(".gs_rt")
            if not heading:
                continue
            heading = BeautifulSoup(str(heading), "html.parser")
            for label in heading.select(".gs_ctc, .gs_ctu"):
                label.decompose()
            anchor = heading.select_one("a[href]")
            results.append({
                "title": heading.get_text(" ", strip=True),
                "link": anchor["href"] if anchor else "",
                "snippet": row.get_text(" ", strip=True),
                "resources": [{"link": a["href"], "file_format": "PDF" if "[PDF]" in a.get_text() else "HTML"}
                              for a in row.select(".gs_or_ggsm a[href]")],
            })
        return results

    def _candidates(self, results, reference):
        candidates, seen = [], set()
        if not isinstance(results, list):
            raise ValueError("Invalid Scholar result list")
        for result in results[:5]:
            if not isinstance(result, dict):
                continue
            title = re.sub(r"^\[(?:PDF|HTML|BOOK|CITATION)\]\s*", "", result.get("title", ""), flags=re.I)
            landing = external_url(result.get("link"))
            if reference.title:
                if not same_title(reference.title, title):
                    continue
            elif not reference.clean_doi or reference.clean_doi.casefold() not in (
                str(result.get("snippet", "")) + " " + (landing or "")
            ).casefold():
                continue
            if landing and conflicts_with_doi(reference, landing):
                continue
            resources = list(result.get("resources") or [])[:5]
            if landing:
                resources.append({"link": landing, "file_format": ""})
            for resource in resources:
                if not isinstance(resource, dict):
                    continue
                url = external_url(resource.get("link"))
                if not url or url in seen or conflicts_with_doi(reference, url):
                    continue
                seen.add(url)
                direct = resource.get("file_format", "").upper() == "PDF" or urlsplit(url).path.lower().endswith(".pdf")
                candidates.append(CandidatePDF(url=url, provider=self.name,
                    landing_page=landing or url, is_direct_pdf=direct))
        candidates.sort(key=lambda candidate: not candidate.is_direct_pdf)
        return candidates[:12]
