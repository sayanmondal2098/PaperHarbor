"""Main application engine orchestrating reference extraction, search, download, and reporting."""

import logging
import time
from pathlib import Path
from typing import Callable, List, Optional

from paperharbor.downloader import PdfDownloader
from paperharbor.providers.landing import LandingPageResolver
from paperharbor.models import CandidatePDF, DownloadResult, PaperStatus, Reference
from paperharbor.namer import generate_filename, get_unique_destination_path
from paperharbor.providers.aggregator import ProviderAggregator
from paperharbor.reporter import Reporter
from paperharbor.zotero.reader_base import ZoteroReaderBase

logger = logging.getLogger(__name__)


class PaperHarborApp:
    """Core application coordinator for PaperHarbor."""

    def __init__(
        self,
        reader: ZoteroReaderBase,
        dest_folder: Path,
        email: Optional[str] = None,
        skip_zotero_has_pdf: bool = True,
        skip_existing_dest: bool = True,
        filename_template: str = "{year}_{author}_{title}.pdf",
        max_title_chars: int = 70,
        report_path: Optional[Path] = None,
        request_delay: float = 0.5,
        progress_callback: Optional[Callable[[int, int, Reference, str], None]] = None,
    ):
        self.reader = reader
        self.dest_folder = Path(dest_folder).resolve()
        self.dest_folder.mkdir(parents=True, exist_ok=True)
        self.skip_zotero_has_pdf = skip_zotero_has_pdf
        self.skip_existing_dest = skip_existing_dest
        self.filename_template = filename_template
        self.max_title_chars = max_title_chars
        self.request_delay = request_delay
        self.progress_callback = progress_callback

        self.aggregator = ProviderAggregator(email=email)
        self.downloader = PdfDownloader()
        self.landing_resolver = LandingPageResolver(self.downloader.session)
        self.reporter = Reporter(output_path=report_path, dest_dir=self.dest_folder)

    def run(
        self,
        collection_filter: Optional[str] = None,
        limit: Optional[int] = None,
        item_keys: Optional[List[str]] = None,
    ) -> Path:
        """
        Execute the full pipeline:
        1. Read references from Zotero.
        2. Identify missing PDFs.
        3. Search Open Access providers.
        4. Download valid PDFs to personal folder.
        5. Generate comprehensive CSV report.
        """
        logger.info("Extracting references from Zotero...")
        # We pass only_missing_pdf=False so we can record already-attached items in report if needed
        references = self.reader.get_references(
            collection_filter=collection_filter,
            only_missing_pdf=False
        )

        total_refs = len(references)
        logger.info(f"Loaded {total_refs} total references from Zotero.")

        if item_keys is not None:
            wanted = set(item_keys)
            references = [r for r in references if r.key in wanted]
            logger.info(f"Processing {len(references)} manually selected references.")

        if limit and limit > 0:
            references = references[:limit]
            logger.info(f"Processing first {len(references)} references (due to --limit {limit}).")

        for idx, ref in enumerate(references, start=1):
            if self.progress_callback:
                self.progress_callback(idx, len(references), ref, "Processing...")

            self._process_single_reference(ref)

            # Polite delay between internet requests
            if self.request_delay > 0:
                time.sleep(self.request_delay)

        report_file = self.reporter.write_csv()
        return report_file

    def _process_single_reference(self, ref: Reference):
        # 1. Check if Zotero already has PDF
        if self.skip_zotero_has_pdf and ref.has_zotero_pdf:
            logger.info(f"[SKIP] '{ref.title[:50]}' already has PDF in Zotero.")
            self.reporter.record(DownloadResult(
                reference=ref,
                status=PaperStatus.SKIPPED_ALREADY_IN_ZOTERO,
                notes=f"Skipped: Already has {len(ref.zotero_attachments)} PDF attachment(s) in Zotero."
            ))
            return

        # 2. Determine target filename and path
        desired_filename = generate_filename(
            ref,
            template=self.filename_template,
            max_title_chars=self.max_title_chars
        )
        target_path = self.dest_folder / desired_filename

        # 3. Check if file already exists in destination folder
        if self.skip_existing_dest and target_path.exists():
            file_size = target_path.stat().st_size
            if file_size > 1024:
                logger.info(f"[SKIP] '{desired_filename}' already exists in personal destination folder.")
                self.reporter.record(DownloadResult(
                    reference=ref,
                    status=PaperStatus.SKIPPED_ALREADY_IN_DEST,
                    saved_filename=desired_filename,
                    saved_path=str(target_path),
                    file_size_bytes=file_size,
                    notes="Skipped: Valid PDF already exists in destination folder."
                ))
                return

        # 4. Search internet for Open Access candidates
        logger.info(f"[SEARCH] Searching Open Access for: '{ref.title[:60]}' (DOI: {ref.clean_doi or 'None'})")
        candidates, publisher_url = self.aggregator.find_candidates(ref)

        if not candidates:
            logger.info(f"[PAYWALL/NOT FOUND] No legal OA PDF found for: '{ref.title[:50]}'")
            self.reporter.record(DownloadResult(
                reference=ref,
                status=PaperStatus.PAYWALLED_OR_OA_NOT_FOUND,
                publisher_url=publisher_url,
                notes="No legal Open Access PDF located. Paper is likely paywalled."
            ))
            return

        # 5. Attempt download waterfall
        download_success = False
        last_error = ""

        # Make sure destination path is unique if collision with different paper
        dest_file = get_unique_destination_path(self.dest_folder, desired_filename, ref.clean_doi)

        attempts = []
        tried = set()
        for cand in candidates:
            if cand.is_direct_pdf:
                attempts.append(cand)
            else:
                # Landing page: look for the actual PDF link on it
                logger.info(f"[RESOLVE] Looking for PDF link on {cand.provider} landing page ({cand.url[:70]}...)")
                for pdf_url in self.landing_resolver.resolve(cand.url):
                    attempts.append(CandidatePDF(
                        url=pdf_url, provider=cand.provider, landing_page=cand.url,
                        oa_status=cand.oa_status, version=cand.version, is_direct_pdf=True,
                    ))

        blocked_urls = []
        for cand in attempts:
            if cand.url in tried:
                continue
            tried.add(cand.url)
            logger.info(f"[DOWNLOADING] Trying {cand.provider} link ({cand.url[:70]}...)")
            success, size_bytes, err = self.downloader.download_pdf(cand.url, dest_file)

            if success:
                logger.info(f"[SUCCESS] Saved to {dest_file.name} ({round(size_bytes/1024, 1)} KB) via {cand.provider}")
                self.reporter.record(DownloadResult(
                    reference=ref,
                    status=PaperStatus.DOWNLOADED,
                    provider=cand.provider,
                    pdf_url=cand.url,
                    saved_filename=dest_file.name,
                    saved_path=str(dest_file),
                    file_size_bytes=size_bytes,
                    publisher_url=publisher_url,
                    notes=f"Successfully downloaded via {cand.provider} ({cand.oa_status or 'OA'})."
                ))
                return
            last_error = err or "Unknown download error"
            if "HTTP 403" in last_error or "HTTP 401" in last_error or "not a valid PDF" in last_error:
                blocked_urls.append(cand.landing_page or cand.url)
            logger.debug(f"[RETRY] Failed candidate {cand.url}: {last_error}")

        # Provider says open access but the site refuses automated downloads: give a manual link
        oa_confirmed = any(c.oa_status and c.oa_status != "publisher" for c in candidates)
        if blocked_urls and oa_confirmed:
            manual = blocked_urls[0]
            logger.warning(f"[MANUAL] Open access but blocked for automation: '{ref.title[:50]}' -> {manual}")
            self.reporter.record(DownloadResult(
                reference=ref,
                status=PaperStatus.OA_BLOCKED_MANUAL,
                publisher_url=manual,
                notes=f"Open-access copy exists but the site blocks automated downloads ({last_error}). "
                      f"Open the link in your browser and save the PDF manually."
            ))
            return

        logger.warning(f"[FAILED] All OA download links failed for '{ref.title[:50]}': {last_error}")
        self.reporter.record(DownloadResult(
            reference=ref,
            status=PaperStatus.DOWNLOAD_FAILED,
            publisher_url=publisher_url,
            notes=f"Found {len(candidates)} candidate URL(s) but download failed: {last_error}"
        ))
