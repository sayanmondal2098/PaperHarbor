"""Robust PDF downloader with streaming and strict PDF header validation."""

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse
import requests

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 (PaperHarbor/1.0)"
)


class PdfDownloader:
    """Downloads PDF files with streaming, timeouts, and byte-level %PDF- verification."""

    def __init__(self, timeout: int = 30, user_agent: Optional[str] = None, retries: int = 2):
        self.timeout = timeout
        self.retries = max(0, retries)
        self.retry_after = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent or DEFAULT_USER_AGENT,
            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        })

    def download_pdf(self, url, destination_path, min_bytes=1024, referer=None):
        """Retry transient failures only; never repeatedly hammer access-denied pages."""
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            return False, 0, "Unsupported PDF URL; use an http or https link."
        result = (False, 0, "No download attempted")
        for attempt in range(self.retries + 1):
            self.retry_after = None
            result = self._download_once(url, destination_path, min_bytes, referer)
            if result[0]:
                return result
            error = result[2] or "Unknown download error"
            transient = any(token in error for token in (
                "HTTP 202", "HTTP 408", "HTTP 425", "HTTP 429", "HTTP 500",
                "HTTP 502", "HTTP 503", "HTTP 504", "Network error", "timed out"
            ))
            if not transient or attempt >= self.retries:
                return result
            delay = self.retry_after if self.retry_after is not None else 2 ** attempt
            if delay > 30:
                return False, result[1], error + f"; server requests a {delay:g}s wait. Retry later."
            logger.info("Transient download failure; retrying in %.1fs: %s", delay, error)
            time.sleep(delay)
        return result

    def _download_once(
        self,
        url: str,
        destination_path: Path,
        min_bytes: int = 1024,
        referer: Optional[str] = None,
    ) -> Tuple[bool, int, Optional[str]]:
        """
        Downloads a PDF from url and saves it to destination_path.

        Performs magic byte inspection (%PDF-) to guarantee the file is an actual PDF
        and not an HTML paywall login page or error banner.

        Returns:
            (success: bool, file_size_bytes: int, error_message: Optional[str])
        """
        destination_path = Path(destination_path)
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        temp_file = destination_path.with_name(f"{destination_path.name}.part_{os.getpid()}")

        try:
            logger.debug(f"Attempting download from: {url}")
            headers = {"Referer": referer} if referer else {}
            with self.session.get(url, stream=True, timeout=self.timeout, allow_redirects=True, headers=headers) as resp:
                retry_after = resp.headers.get("Retry-After")
                if isinstance(retry_after, str) and retry_after.isdigit():
                    self.retry_after = float(retry_after)
                if resp.status_code not in (200, 202):
                    return False, 0, f"HTTP {resp.status_code} ({resp.reason})"

                chunk_iter = iter(resp.iter_content(chunk_size=8192))
                prefix = []
                prefix_size = 0
                for chunk in chunk_iter:
                    if chunk:
                        prefix.append(chunk)
                        prefix_size += len(chunk)
                    if prefix_size >= 1024:
                        break
                first_chunk = b"".join(prefix)
                if not first_chunk:
                    if resp.status_code == 202:
                        return False, 0, "HTTP 202 (Accepted): server has not supplied a PDF yet"
                    return False, 0, "Empty response body from server"
                if b"%PDF-" not in first_chunk[:1024]:
                    if resp.status_code == 202:
                        return False, 0, "HTTP 202 (Accepted): server returned a processing/challenge page, not a PDF"
                    return False, 0, "Response is not a valid PDF; an HTML viewer, sign-in, or anti-bot page was returned"

                # Stream to temporary file
                total_bytes = len(first_chunk)
                with open(temp_file, "wb") as f:
                    f.write(first_chunk)
                    for chunk in chunk_iter:
                        if chunk:
                            f.write(chunk)
                            total_bytes += len(chunk)

                if total_bytes < min_bytes:
                    if temp_file.exists():
                        temp_file.unlink()
                    return False, total_bytes, f"Downloaded file too small ({total_bytes} bytes), likely corrupted"

            # Atomic move from temp to destination
            shutil.move(str(temp_file), str(destination_path))
            return True, total_bytes, None

        except requests.Timeout:
            if temp_file.exists():
                temp_file.unlink()
            return False, 0, f"Connection timed out after {self.timeout}s"
        except requests.RequestException as e:
            if temp_file.exists():
                temp_file.unlink()
            return False, 0, f"Network error: {type(e).__name__}: {str(e) or 'connection interrupted'}"
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            return False, 0, f"Unexpected error: {str(e)}"
