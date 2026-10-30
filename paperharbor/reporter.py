"""CSV reporting and statistics generation for paper downloads."""

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from paperharbor.models import DownloadResult, PaperStatus

logger = logging.getLogger(__name__)

CSV_HEADERS = [
    "Item_Key",
    "Status",
    "First_Author",
    "Year",
    "Title",
    "DOI",
    "Source_Provider",
    "Saved_Filename",
    "Saved_Path",
    "File_Size_KB",
    "PDF_URL",
    "Publisher_Or_Landing_URL",
    "Notes",
]


class Reporter:
    """Writes download outcomes to a structured CSV file and computes summary statistics."""

    def __init__(self, output_path: Optional[Path] = None, dest_dir: Optional[Path] = None):
        if output_path:
            self.output_path = Path(output_path).resolve()
        else:
            folder = Path(dest_dir) if dest_dir else Path.cwd()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.output_path = folder / f"paperharbor_report_{timestamp}.csv"

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.results: List[DownloadResult] = []

    def record(self, result: DownloadResult):
        """Append a result."""
        self.results.append(result)

    def write_csv(self) -> Path:
        """Write all recorded results to the CSV report file."""
        with open(self.output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()

            for res in self.results:
                ref = res.reference
                file_size_kb = round(res.file_size_bytes / 1024, 2) if res.file_size_bytes > 0 else 0
                row = {
                    "Item_Key": ref.key,
                    "Status": res.status.value,
                    "First_Author": ref.display_author,
                    "Year": ref.display_year,
                    "Title": ref.title,
                    "DOI": ref.clean_doi or "",
                    "Source_Provider": res.provider or "",
                    "Saved_Filename": res.saved_filename or "",
                    "Saved_Path": str(res.saved_path) if res.saved_path else "",
                    "File_Size_KB": file_size_kb if file_size_kb > 0 else "",
                    "PDF_URL": res.pdf_url or "",
                    "Publisher_Or_Landing_URL": res.publisher_url or ref.publisher_url or "",
                    "Notes": res.notes or "",
                }
                writer.writerow(row)

        logger.info(f"Report written to: {self.output_path}")
        return self.output_path

    def get_summary(self) -> Dict[str, int]:
        """Calculates counts by status category."""
        counts = {
            "TOTAL_REFERENCES": len(self.results),
            PaperStatus.DOWNLOADED.value: 0,
            PaperStatus.SKIPPED_ALREADY_IN_ZOTERO.value: 0,
            PaperStatus.SKIPPED_ALREADY_IN_DEST.value: 0,
            PaperStatus.PAYWALLED_OR_OA_NOT_FOUND.value: 0,
            PaperStatus.DOWNLOAD_FAILED.value: 0,
            PaperStatus.OA_BLOCKED_MANUAL.value: 0,
            PaperStatus.ERROR.value: 0,
        }

        for res in self.results:
            counts[res.status.value] = counts.get(res.status.value, 0) + 1

        return counts
