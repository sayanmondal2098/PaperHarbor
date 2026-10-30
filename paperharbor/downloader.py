"""Robust PDF downloader with streaming and strict PDF header validation."""

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Tuple
import requests

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 (PaperHarbor/1.0)"
)


class PdfDownloader:
    """Downloads PDF files with streaming, timeouts, and byte-level %PDF- verification."""

    def __init__(self, timeout: int = 30, user_agent: Optional[str] = None):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent or DEFAULT_USER_AGENT,
            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
        })

    def download_pdf(
        self,
        url: str,
        destination_path: Path,
        min_bytes: int = 1024
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
            with self.session.get(url, stream=True, timeout=self.timeout, allow_redirects=True) as resp:
                if resp.status_code != 200:
                    return False, 0, f"HTTP {resp.status_code} ({resp.reason})"

                # Read first chunk to inspect header
                chunk_iter = iter(resp.iter_content(chunk_size=8192))
                try:
                    first_chunk = next(chunk_iter)
                except StopIteration:
                    return False, 0, "Empty response body from server"

                # Check for PDF magic bytes in the first 1024 bytes (some servers have UTF-8 BOM or leading comments)
                header_slice = first_chunk[:1024]
                if b"%PDF-" not in header_slice:
                    # Often paywalled sites return HTML error page with status 200
                    sample_text = header_slice[:100].decode("latin-1", errors="replace").replace("\n", " ")
                    return False, 0, f"Response is not a valid PDF (header was: '{sample_text}...') - likely paywalled or login portal"

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
            return False, 0, f"Network error: {str(e)}"
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            return False, 0, f"Unexpected error: {str(e)}"
