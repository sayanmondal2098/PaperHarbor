# PaperHarbor 🚢📄

**Bulk Open-Access PDF Downloader for Zotero Libraries**

PaperHarbor connects to your Zotero library, detects references that lack PDF attachments, discovers legally accessible full-text PDFs across Open Access repositories (Unpaywall, OpenAlex, arXiv, Europe PMC, Semantic Scholar, Crossref), and downloads them into a **personal folder completely separate from Zotero** (e.g. `D:\Research\Papers\`).

---

## 🎯 Key Distinction

> **Zotero is strictly the reference source.**
> **Your personal directory is the download destination.**
>
> PaperHarbor **never modifies, writes to, or locks your Zotero library**. It reads your database safely via a read-only snapshot, leaving your existing Zotero database completely untouched.

---

## ✨ Features

1. **Zotero Library Reader**:
   - Automatically detects your default `zotero.sqlite` on Windows (`%USERPROFILE%\Zotero`), macOS, and Linux.
   - Non-intrusive: creates an instantaneous read-only snapshot before querying, avoiding SQLite lock errors even while Zotero is running.
   - Also supports **CSL-JSON** (`.json`), **BibTeX** (`.bib`), and the **Zotero Web API**.
2. **Missing PDF Detection**:
   - Inspects `itemAttachments` for `application/pdf` and `.pdf` files.
   - Skips references that already have attachments in Zotero (saving bandwidth and time).
3. **Multi-Source Open Access Waterfall**:
   - **Unpaywall**: Direct access to 50,000+ OA journals and repositories using DOIs.
   - **OpenAlex**: Searches 250M+ scholarly works by DOI or Title fallback.
   - **arXiv**: Direct PDF resolution from arXiv DOIs, IDs, URLs, and title queries.
   - **Europe PMC**: Biomedical & PubMed Central open access full-text articles.
   - **Semantic Scholar**: Open access PDF resolution.
   - **Crossref**: Direct publisher open access links (MDPI, SpringerOpen, PLOS, etc.).
4. **Byte-Level PDF Verification**:
   - Performs magic-byte inspection (`%PDF-` header check).
   - Automatically rejects HTML paywall login portals, Cloudflare splash pages, or error banners that return HTTP 200.
5. **Clean File Organization**:
   - Standardizes filenames to `{Year}_{Author}_{SanitizedTitle}.pdf` (e.g. `2025_Smith_Phishing_Detection.pdf`).
   - Removes invalid OS characters (`:`, `\`, `/`, `?`, `*`), converts accented characters (`Müller` -> `Muller`), and caps title length to avoid Windows 260-character path limits.
   - Handles name collisions with automatic numerical suffixes (`_1`, `_2`).
6. **Detailed CSV Status Report**:
   - Produces a comprehensive CSV report recording:
     - `Item_Key`, `Status`, `First_Author`, `Year`, `Title`, `DOI`
     - `Source_Provider` (Unpaywall, OpenAlex, arXiv, etc.)
     - `Saved_Filename` & `Saved_Path`
     - `Publisher_Or_Landing_URL` (official DOI landing page for paywalled papers)
     - `Notes` (error details or status explanations)

---

## 🚀 Quick Start

### 1. Requirements

- Python 3.8 or later
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  ```

### 2. Basic Command

Download all missing PDFs to your personal research directory:

```bash
python main.py -d "D:\Research\Papers"
```

If PaperHarbor finds your default Zotero database, it will immediately begin processing.

---

## 📖 CLI Usage & Options

```
python main.py -h
```

| Argument | Description | Default |
| :--- | :--- | :--- |
| `-d`, `--dest-folder` | **Required.** Destination directory for PDFs (e.g. `D:\Research\Papers`). | *Required* |
| `-z`, `--zotero-path` | Explicit path to `zotero.sqlite`. | Auto-detected |
| `-e`, `--email` | Contact email for OpenAlex & Unpaywall polite API requests. | `paperharbor.downloader@gmail.com` |
| `-c`, `--collection` | Filter references to a specific Zotero collection name. | Process all |
| `-l`, `--limit` | Process only the first N references (useful for testing). | No limit |
| `-r`, `--report` | Custom path for the generated CSV report. | `{dest_folder}/paperharbor_report_TIMESTAMP.csv` |
| `--include-zotero-has-pdf` | Download papers even if Zotero already has an attached PDF. | `False` (Skip) |
| `--force-redownload` | Redownload even if PDF exists in destination folder. | `False` (Skip) |
| `--template` | Custom filename pattern (`{year}`, `{author}`, `{title}`). | `{year}_{author}_{title}.pdf` |
| `--export-file` | Path to exported CSL-JSON (`.json`) or BibTeX (`.bib`) file. | None |
| `--api-key` | Zotero Web API Key. | None |
| `--user-id` | Zotero User ID for Web API. | None |
| `-v`, `--verbose` | Enable verbose debug output. | `False` |

---

## 💡 Practical Examples

### 1. Filter by Zotero Collection
To only process papers in your "Phishing" or "Thesis" collection:
```bash
python main.py -d "D:\Research\Papers" --collection "Phishing"
```

### 2. Test a Batch of 5 Papers
```bash
python main.py -d "D:\Research\Papers" --limit 5
```

### 3. Specify Custom Zotero SQLite Location
```bash
python main.py -d "D:\Research\Papers" -z "C:\Users\YourName\Zotero\zotero.sqlite"
```

### 4. Use an Exported Zotero Collection (`.json` or `.bib`)
Right-click your collection in Zotero -> **Export Collection...** -> choose **CSL JSON** or **BibTeX**:
```bash
python main.py -d "D:\Research\Papers" --export-file "my_collection.json"
```

### 5. Access via Zotero Web API
For cloud-synced or group libraries without local access:
```bash
python main.py -d "D:\Research\Papers" --api-key "YOUR_KEY" --user-id "YOUR_USER_ID"
```

---

## 📊 CSV Report Format

Every run outputs a CSV log with the following columns:

| Column | Description |
| :--- | :--- |
| `Item_Key` | Zotero reference key |
| `Status` | `DOWNLOADED`, `SKIPPED_ALREADY_IN_ZOTERO`, `SKIPPED_ALREADY_IN_DEST`, `PAYWALLED_OR_OA_NOT_FOUND`, `DOWNLOAD_FAILED` |
| `First_Author` | First author's surname (e.g. `Smith`) |
| `Year` | Publication year (e.g. `2025`) |
| `Title` | Title of paper |
| `DOI` | Clean DOI identifier |
| `Source_Provider` | Discovered provider (`Unpaywall`, `OpenAlex`, `arXiv`, `Europe PMC`, `Crossref`) |
| `Saved_Filename` | Generated filename (`2025_Smith_Phishing_Detection.pdf`) |
| `Saved_Path` | Absolute path in your personal directory |
| `File_Size_KB` | File size in kilobytes |
| `PDF_URL` | Direct URL used to download the PDF |
| `Publisher_Or_Landing_URL` | DOI landing page (ideal for paywalled papers) |
| `Notes` | Error diagnostics or status notes |

---

## 🔒 Paywall Note

Legally accessible Open Access papers (Green, Gold, Bronze, Hybrid, and Preprints) are downloaded automatically. For subscription-restricted / paywalled articles, PaperHarbor records the publisher's landing page (`https://doi.org/...`) in your CSV report so you can access them through your institution's proxy or library subscription.

---

## 🧪 Running Tests

To run the unit and integration tests:

```bash
python -m unittest discover tests
```

## Web UI

Run `python web.py` (optionally `--port 8765 --no-browser`) and open http://127.0.0.1:8765/. The server binds to localhost only.
