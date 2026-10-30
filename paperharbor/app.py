"""Main application engine orchestrating reference extraction, search, download, and reporting."""

import logging
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Optional

from paperharbor.downloader import PdfDownloader
from paperharbor.providers.landing import LandingPageResolver, is_known_oa_host
from paperharbor.models import CandidatePDF, DownloadResult, PaperStatus, Reference
from paperharbor.namer import generate_filename, get_unique_destination_path
from paperharbor.providers.aggregator import ProviderAggregator
from paperharbor.reporter import Reporter
from paperharbor.recovery import recovery_action, web_resource_kind
from paperharbor.providers.matching import conflicts_with_doi
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
        pdf_overrides: Optional[dict] = None,
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
        self.pdf_overrides = pdf_overrides or {}
        if not isinstance(self.pdf_overrides, dict):
            raise ValueError("Alternate PDF links must be a mapping of item keys/DOIs to URLs.")
        for value in self.pdf_overrides.values():
            urls = [value] if isinstance(value, str) else value
            if not isinstance(urls, list) or any(not isinstance(url, str) or not url.startswith(("http://", "https://")) for url in urls):
                raise ValueError("Use http(s) URLs for alternate PDF links.")

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

        outcomes = {}
        for idx, ref in enumerate(references, start=1):
            if self.progress_callback:
                self.progress_callback(idx, len(references), ref, "Processing...")

            try:
                overrides = self.pdf_overrides.get(ref.key) or self.pdf_overrides.get(ref.clean_doi) or []
                cache_key = (ref.clean_doi.lower(), repr(overrides)) if ref.clean_doi else None
                cached = outcomes.get(cache_key) if cache_key else None
                if cached and not (self.skip_zotero_has_pdf and ref.has_zotero_pdf):
                    status = PaperStatus.SKIPPED_ALREADY_IN_DEST if cached.status == PaperStatus.DOWNLOADED else cached.status
                    self.reporter.record(replace(cached, reference=ref, status=status,
                        notes=cached.notes + " Reused the same DOI outcome from this run; duplicate network requests were avoided."))
                else:
                    self._process_single_reference(ref)
                    if cache_key and self.reporter.results and self.reporter.results[-1].reference is ref and self.reporter.results[-1].status in (
                        PaperStatus.DOWNLOADED, PaperStatus.DOWNLOAD_FAILED, PaperStatus.OA_BLOCKED_MANUAL,
                        PaperStatus.PAYWALLED_OR_OA_NOT_FOUND, PaperStatus.WITHDRAWN,
                    ):
                        outcomes[cache_key] = self.reporter.results[-1]
            except Exception as exc:
                logger.exception("Reference failed; continuing with the next paper: %s", ref.key)
                self.reporter.record(DownloadResult(reference=ref, status=PaperStatus.ERROR,
                    publisher_url=ref.publisher_url, notes=f"{type(exc).__name__}: {exc}",
                    recovery_action=recovery_action("ERROR")))

            # Polite delay between internet requests
            if self.request_delay > 0:
                time.sleep(self.request_delay)

        report_file = self.reporter.write_csv()
        return report_file

    def _process_single_reference(self, ref: Reference):
        resource_kind = web_resource_kind(ref)
        if resource_kind:
            self.reporter.record(DownloadResult(reference=ref, status=PaperStatus.WEB_RESOURCE,
                publisher_url=ref.url, notes=f"{resource_kind} reference retained as a link; no PDF was requested.",
                recovery_action=recovery_action("WEB_RESOURCE")))
            return
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
            with target_path.open("rb") as existing:
                valid_header = b"%PDF-" in existing.read(1024)
            if file_size > 1024 and valid_header:
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

        logger.info("[SEARCH] %s (DOI: %s)", ref.title[:70], ref.clean_doi or "None")
        candidates, publisher_url = self.aggregator.find_candidates(ref)
        preferred = self.pdf_overrides.get(ref.key) or self.pdf_overrides.get(ref.clean_doi) or []
        if isinstance(preferred, str):
            preferred = [preferred]
        candidates = [CandidatePDF(url=url, provider="User supplied", landing_page=url)
                      for url in preferred] + candidates
        dest_file = get_unique_destination_path(self.dest_folder, desired_filename, ref.clean_doi)
        attempts, blocked = [], []
        withdrawal_note = ""
        tried, resolved = set(), set()
        discovered = len(candidates)

        def log_attempt(candidate, stage, error):
            attempts.append({"provider": candidate.provider, "url": candidate.url,
                             "stage": stage, "error": error})
            logger.info("[%s] %s: %s", stage.upper(), candidate.provider, error)
            if any(token in error for token in ("HTTP 401", "HTTP 403", "HTTP 202", "not a valid PDF")):
                oa = candidate.oa_status in ("gold", "green", "hybrid", "bronze", "open")
                if oa or is_known_oa_host(candidate.url) or is_known_oa_host(candidate.landing_page or ""):
                    blocked.append(candidate.landing_page or candidate.url)

        def resolve(candidate):
            nonlocal withdrawal_note
            if candidate.url in resolved:
                return []
            resolved.add(candidate.url)
            urls = self.landing_resolver.resolve(candidate.url, expected_doi=ref.clean_doi,
                                                 expected_title=ref.title)
            if self.landing_resolver.last_error.startswith("Withdrawn arXiv record"):
                withdrawal_note = self.landing_resolver.last_error
                log_attempt(candidate, "withdrawal", withdrawal_note)
                return []
            if self.landing_resolver.last_error.startswith("Rejected page"):
                log_attempt(candidate, "resolve", self.landing_resolver.last_error)
                return []
            if not urls:
                log_attempt(candidate, "resolve", self.landing_resolver.last_error or "No PDF link on article page")
            return [CandidatePDF(url=url, provider=candidate.provider, landing_page=candidate.url,
                oa_status=candidate.oa_status, version=candidate.version) for url in urls]

        def record_withdrawal():
            if not withdrawal_note:
                return False
            self.reporter.record(DownloadResult(reference=ref, status=PaperStatus.WITHDRAWN,
                publisher_url=ref.url or ref.publisher_url, notes=withdrawal_note,
                attempts=attempts, recovery_action=recovery_action("WITHDRAWN")))
            return True

        for phase in range(2):
            if phase:
                logger.info("[FALLBACK] Trying remaining providers and publisher metadata for %s", ref.key)
                candidates = self.aggregator.find_fallback_candidates(ref)
                discovered += len(candidates)
            pending = list(candidates)
            while pending:
                candidate = pending.pop(0)
                if conflicts_with_doi(ref, candidate.url) or conflicts_with_doi(ref, candidate.landing_page):
                    log_attempt(candidate, "identity", "Rejected candidate with a conflicting DOI")
                    continue
                if not candidate.is_direct_pdf:
                    pending.extend(resolve(candidate))
                    if record_withdrawal():
                        return
                    continue
                if candidate.url in tried:
                    continue
                tried.add(candidate.url)
                logger.info("[DOWNLOADING] %s: %s", candidate.provider, candidate.url)
                success, size_bytes, error = self.downloader.download_pdf(
                    candidate.url, dest_file, referer=candidate.landing_page, expected_doi=ref.clean_doi)
                if success:
                    attempts.append({"provider": candidate.provider, "url": candidate.url,
                                     "stage": "download", "error": "", "outcome": "downloaded"})
                    self.reporter.record(DownloadResult(reference=ref, status=PaperStatus.DOWNLOADED,
                        provider=candidate.provider, pdf_url=candidate.url, saved_filename=dest_file.name,
                        saved_path=str(dest_file), file_size_bytes=size_bytes, publisher_url=publisher_url,
                        notes=f"Downloaded via {candidate.provider} ({candidate.version or candidate.oa_status or 'version unspecified'}).",
                        attempts=attempts, recovery_action=recovery_action("DOWNLOADED")))
                    return
                error = error or "Unknown download error"
                log_attempt(candidate, "download", error)
                # A provider's 'PDF URL' can actually be a viewer page. Inspect it once.
                if "not a valid PDF" in error:
                    pending.extend(resolve(candidate))
                    if record_withdrawal():
                        return
                # A stale PDF URL may have a current replacement on its article page.
                if candidate.landing_page and candidate.landing_page != candidate.url:
                    pending.extend(resolve(CandidatePDF(url=candidate.landing_page,
                        provider=candidate.provider, oa_status=candidate.oa_status, is_direct_pdf=False)))
                    if record_withdrawal():
                        return

        for error in self.aggregator.errors:
            attempts.append({"provider": "Discovery", "url": "", "stage": "search", "error": error})
        errors = "; ".join(dict.fromkeys(a["error"] for a in attempts if a.get("error")))
        if blocked:
            status = PaperStatus.OA_BLOCKED_MANUAL
            publisher_url = blocked[0]
            notes = "An apparent open-access location blocked automated access. Other available sources were also tried."
        elif tried or any(token in errors for token in ("HTTP 202", "HTTP 401", "HTTP 403", "HTTP 429", "HTTP 5", "timed out", "ConnectionError")):
            status = PaperStatus.DOWNLOAD_FAILED
            notes = f"Tried {len(tried)} unique PDF URL(s) from {discovered} candidates; no download succeeded."
        else:
            status = PaperStatus.PAYWALLED_OR_OA_NOT_FOUND
            notes = "No usable PDF link found after expanded discovery. This does not prove the paper is paywalled."
        if errors:
            notes += " " + errors
        self.reporter.record(DownloadResult(reference=ref, status=status,
            publisher_url=publisher_url, notes=notes, attempts=attempts,
            suggested_filename=desired_filename, recovery_action=recovery_action(status.value, errors)))
