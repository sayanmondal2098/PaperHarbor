"""Command line interface for PaperHarbor."""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from paperharbor.app import PaperHarborApp
from paperharbor.models import PaperStatus
from paperharbor.zotero.api_reader import ZoteroApiReader
from paperharbor.zotero.export_reader import ZoteroExportReader
from paperharbor.zotero.sqlite_reader import ZoteroSqliteReader, find_default_zotero_db

BANNER = r"""
========================================================================
     ____                         _   _             _                 
    |  _ \ __ _ _ __   ___ _ __  | | | | __ _ _ __ | |__   ___  _ __  
    | |_) / _` | '_ \ / _ \ '__| | |_| |/ _` | '__|| '_ \ / _ \| '__| 
    |  __/ (_| | |_) |  __/ |    |  _  | (_| | |   | |_) | (_) | |    
    |_|   \__,_| .__/ \___|_|    |_| |_|\__,_|_|   |_.__/ \___/|_|    
               |_|                                                    
    Bulk Open-Access PDF Downloader for Zotero Libraries
========================================================================
"""


def setup_logging(verbose: bool = False):
    """Configures logging format and level."""
    log_level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = [handler]
    
    # Suppress verbose urllib3 logs unless extra verbose
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def parse_args(args: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PaperHarbor: Extract references from Zotero and download Open Access PDFs to your personal folder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect local Zotero and download missing PDFs to D:\\Research\\Papers:
  python main.py -d "D:\\Research\\Papers"

  # Specify exact zotero.sqlite location:
  python main.py -d "D:\\Research\\Papers" -z "C:\\Users\\Name\\Zotero\\zotero.sqlite"

  # Filter by Zotero collection name:
  python main.py -d "D:\\Research\\Papers" --collection "Phishing"

  # Use exported CSL-JSON or BibTeX:
  python main.py -d "D:\\Research\\Papers" --export-file "library.json"

  # Download using Zotero Web API:
  python main.py -d "D:\\Research\\Papers" --api-key "xxxx" --user-id "123456"
"""
    )

    parser.add_argument(
        "-d", "--dest-folder",
        type=str,
        required=True,
        help="Destination folder for downloaded PDFs (completely separate from Zotero, e.g. D:\\Research\\Papers)"
    )

    parser.add_argument(
        "-z", "--zotero-path",
        type=str,
        default=None,
        help="Path to zotero.sqlite (if omitted, searches standard OS locations automatically)"
    )

    parser.add_argument(
        "-e", "--email",
        type=str,
        default="paperharbor.downloader@gmail.com",
        help="Contact email for polite OpenAlex and Unpaywall API requests"
    )

    parser.add_argument(
        "-c", "--collection",
        type=str,
        default=None,
        help="Filter references to a specific Zotero collection name"
    )

    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=None,
        help="Maximum number of references to process (useful for batch testing)"
    )

    parser.add_argument(
        "-r", "--report",
        type=str,
        default=None,
        help="Custom destination path for CSV report (defaults to {dest_folder}/paperharbor_report_TIMESTAMP.csv)"
    )

    parser.add_argument(
        "--include-zotero-has-pdf",
        action="store_true",
        default=False,
        help="Also download papers that already have PDF attachments in Zotero (default is to skip them)"
    )

    parser.add_argument(
        "--force-redownload",
        action="store_true",
        default=False,
        help="Redownload papers even if they already exist in the destination folder"
    )

    parser.add_argument(
        "--template",
        type=str,
        default="{year}_{author}_{title}.pdf",
        help="Filename formatting template (default: '{year}_{author}_{title}.pdf')"
    )

    parser.add_argument(
        "--export-file",
        type=str,
        default=None,
        help="Path to exported CSL-JSON (.json) or BibTeX (.bib) file instead of SQLite"
    )

    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Zotero Web API Key (for cloud syncing without local sqlite)"
    )

    parser.add_argument(
        "--user-id",
        type=str,
        default=None,
        help="Zotero User ID for Web API"
    )

    parser.add_argument(
        "--group-id",
        type=str,
        default=None,
        help="Zotero Group ID for Web API"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose debug logging"
    )

    return parser.parse_args(args)


def run_cli(args: Optional[list] = None) -> int:
    parsed = parse_args(args)
    setup_logging(parsed.verbose)

    print(BANNER)

    dest_folder = Path(parsed.dest_folder)
    print(f"[*] Destination Folder: {dest_folder.resolve()}")
    print(f"[*] Filename Pattern:   {parsed.template}")
    print(f"[*] Skip Zotero PDFs:   {'No (Include)' if parsed.include_zotero_has_pdf else 'Yes (Skip)'}")
    print(f"[*] Skip Existing Dest: {'No (Force redownload)' if parsed.force_redownload else 'Yes'}")

    # Determine reader
    try:
        if parsed.export_file:
            print(f"[*] Reading exported file: {parsed.export_file}")
            reader = ZoteroExportReader(Path(parsed.export_file))
        elif parsed.api_key:
            print(f"[*] Connecting to Zotero Web API...")
            reader = ZoteroApiReader(
                api_key=parsed.api_key,
                user_id=parsed.user_id,
                group_id=parsed.group_id
            )
        else:
            db_path = Path(parsed.zotero_path) if parsed.zotero_path else None
            if not db_path:
                detected = find_default_zotero_db()
                if not detected:
                    print("\n[!] Error: Could not automatically detect 'zotero.sqlite'.")
                    print("    Please provide the path using: --zotero-path \"C:\\Path\\To\\Zotero\\zotero.sqlite\"")
                    print("    Or export your collection from Zotero to .json/.bib and use: --export-file \"export.json\"\n")
                    return 1
                db_path = detected
            print(f"[*] Reading local Zotero DB: {db_path} (Read-only safe snapshot)")
            reader = ZoteroSqliteReader(db_path=db_path)

    except Exception as e:
        print(f"\n[!] Failed to initialize Zotero reader: {e}\n")
        return 1

    app = PaperHarborApp(
        reader=reader,
        dest_folder=dest_folder,
        email=parsed.email,
        skip_zotero_has_pdf=not parsed.include_zotero_has_pdf,
        skip_existing_dest=not parsed.force_redownload,
        filename_template=parsed.template,
        report_path=Path(parsed.report) if parsed.report else None,
    )

    try:
        report_path = app.run(
            collection_filter=parsed.collection,
            limit=parsed.limit
        )

        summary = app.reporter.get_summary()

        print("\n" + "=" * 60)
        print("                  DOWNLOAD SUMMARY                   ")
        print("=" * 60)
        print(f"  Total references evaluated:       {summary['TOTAL_REFERENCES']}")
        print(f"  - Skipped (already in Zotero):    {summary[PaperStatus.SKIPPED_ALREADY_IN_ZOTERO.value]}")
        print(f"  - Skipped (already in dest):      {summary[PaperStatus.SKIPPED_ALREADY_IN_DEST.value]}")
        print(f"  - Successfully Downloaded:        {summary[PaperStatus.DOWNLOADED.value]}")
        print(f"  - Paywalled / No OA Found:        {summary[PaperStatus.PAYWALLED_OR_OA_NOT_FOUND.value]}")
        print(f"  - Download Attempt Failed:        {summary[PaperStatus.DOWNLOAD_FAILED.value]}")
        if summary.get(PaperStatus.ERROR.value, 0) > 0:
            print(f"  - Errors encountered:             {summary[PaperStatus.ERROR.value]}")
        print("-" * 60)
        print(f"  Destination Folder: {dest_folder.resolve()}")
        print(f"  Detailed CSV Report: {report_path.resolve()}")
        print("=" * 60 + "\n")
        return 0

    except KeyboardInterrupt:
        print("\n[!] Operation cancelled by user. Partial report saved.")
        app.reporter.write_csv()
        return 130
    except Exception as e:
        logging.exception(f"Unexpected fatal error: {e}")
        return 1
