# ACM and publisher download walkthrough

PaperHarbor accepts any well-formed ACM DOI or article URL as input. It attempts publisher and available author/repository copies and records the result. **Input support does not guarantee a PDF download:** publisher access controls, missing copies, service outages, and withdrawn records can still prevent one.

The workflow applies to ACM research articles, conference papers, posters, and other DOI-backed records. Non-ACM DOIs use the same discovery pipeline and the appropriate providers. The small reviewed author-copy catalog supplements discovery; it is not a mirror of every ACM publication.

## 1. Start the current version

From the repository root, after installing requirements:

```powershell
python web.py
```

If a previous server is running, stop it in its terminal with `Ctrl+C`, start it again, then refresh the browser. A browser refresh alone does not reload Python modules. The interface shows a restart notice when it detects changed code or an older server.

You can inspect the running server:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/runtime
```

`restart_required: false` means the running server's code/catalog/HTML fingerprint matches the files on disk. It does not certify publisher availability.

## 2. Identify the paper

Use the DOI from the article page or exported citation. For example, all of these identify the same ACM work:

```text
10.1145/1557019.1557153
DOI: 10.1145/1557019.1557153
https://doi.org/10.1145/1557019.1557153
https://doi.acm.org/10.1145/1557019.1557153
https://dl.acm.org/doi/10.1145/1557019.1557153
https://dl.acm.org/doi/abs/10.1145/1557019.1557153
https://dl.acm.org/doi/epdf/10.1145/1557019.1557153
```

Replace this example with your paper's DOI or URL. DOI case and recognized URL wrappers are normalized. Legacy `citation.cfm` links can work when redirects or article metadata are available; if they are blocked, use the canonical DOI from the citation rather than guessing the DOI prefix.

## 3. Download through the web interface

1. Open `http://127.0.0.1:8765/`.
2. Choose **Single paper · DOI or URL**.
3. Paste the DOI or article URL.
4. Leave **Paper title** blank to retrieve bibliographic metadata. If the metadata service cannot be reached, enter the actual title as a fallback.
5. Click **Load references**. Check the displayed title and DOI.
6. Select the paper using its checkbox or **Select all**.
7. Choose a destination folder.
8. Click **Download 1 selected reference**.
9. Read the outcome in **Download activity**. Expand **Attempt details** to see the attempted providers, URLs, and errors.

For multiple papers, use a Zotero library or upload a `.bib`, `.bibtex`, or CSL-JSON `.json` bibliography. The same ACM and publisher helpers apply to each selected reference. A previous PaperHarbor CSV report can also be uploaded to retry unresolved outcomes.

## 4. Download through the CLI

No Zotero library or export is required for a single paper:

```powershell
python main.py --doi "10.1145/1557019.1557153" --dest-folder "D:\Research\Papers"
```

An article URL works too:

```powershell
python main.py --url "https://dl.acm.org/doi/abs/10.1145/1961189.1961202" --dest-folder "D:\Research\Papers"
```

If metadata is temporarily unavailable, provide the paper title:

```powershell
python main.py --doi "10.1145/1557019.1557153" --title "Beyond Blacklists: Learning to Detect Malicious Web Sites from Suspicious URLs" --dest-folder "D:\Research\Papers" --verbose
```

Use `python -m paperharbor` instead of `python main.py` if preferred. `--doi` and `--url` are mutually exclusive. Direct single-paper input takes precedence over retry-report, export, API, and SQLite source options.

The destination is created if needed. The default filename uses year, first-author surname, and title. Names may differ when the metadata service returns an abbreviated title. If you supply only a fallback title, missing author/year metadata uses the normal fallback filename components.

## 5. Inspect discovery without downloading

The diagnostic helper prints JSON and does not save PDFs or modify Zotero:

```powershell
python -m paperharbor.diagnose "10.1145/1557019.1557153"
python -m paperharbor.diagnose "https://dl.acm.org/doi/10.1145/1557019.1557153" --expanded
```

Use `--title "Actual paper title"` if metadata is unavailable. `--expanded` also queries fallback providers.

Check:

| Field | Interpretation |
| --- | --- |
| `reference` | Resolved title, DOI, authors, year, and source URL |
| `candidates` | Deduplicated URLs and provider metadata |
| `is_direct_pdf` | Whether the candidate is expected to be a PDF or still needs page resolution |
| `provider_errors` | Rate limits, service failures, or rejected discovery results |
| `rejected_doi_conflicts` | Candidate URLs rejected for identifying a different DOI |

**A candidate is not a confirmed download.** The helper does not fetch and validate candidate PDFs. Run a normal download and inspect its CSV report to confirm success.

## 6. Understand the automatic sequence

1. Normalize the identifier and load reference metadata when needed.
2. Try an exact-DOI reviewed author/conference copy if the catalog contains one.
3. Try ACM PDF/article/ePDF routes and early OA discovery results.
4. Resolve article metadata, supported publisher viewers, and repository links.
5. Reject conflicting DOI candidates and redirects. On author publication lists, prefer a matching title rather than unrelated paper or slide links.
6. Check PDF headers and minimum size before keeping the file.
7. Retry transient network/HTTP failures with bounded backoff. Metadata services that return HTTP 429 receive a cooldown so every subsequent reference does not immediately repeat the request.
8. If initial downloads fail, query remaining discovery providers and inspect available publisher/repository pages.
9. Save a successful PDF, or record the unresolved outcome with diagnostics and a next action.

DOI checks reduce wrong-paper downloads; they do not perform semantic verification of PDF contents. Check the title, authors, and manuscript version before relying on a downloaded copy.

## 7. Handle a blocked ACM paper

HTTP 403 from ACM does not prove that a paper is paywalled, and it does not become downloadable merely because its DOI is valid.

1. Inspect **Attempt details** to see whether an author/repository copy was tried.
2. Use the result's author/conference link when available.
3. Search for the exact DOI/title on an author or institutional publication page.
4. Verify that any alternate PDF is the intended work, not a related paper, talk, supplement, or bibliography.
5. Expand **Use another PDF link** beneath the reference, paste the direct URL, and retry.
6. If no automated route works, open the normal ACM article page in your browser and use its download control or ordinary institutional access.
7. Save a browser download to the destination using the displayed suggested filename. A later normal run skips a matching PDF larger than 1,024 bytes.

For a CLI alternate, create `pdf_overrides.json` with a verified link:

```json
{
  "10.1145/1557019.1557153": "https://cseweb.ucsd.edu/~jtma/papers/beyondbl-kdd2009.pdf"
}
```

Then run:

```powershell
python main.py --doi "10.1145/1557019.1557153" --dest-folder "D:\Research\Papers" --pdf-overrides "pdf_overrides.json"
```

Replace the DOI and URL together for another paper. `--force-redownload` bypasses existing-file skipping while preserving existing files with numbered filenames; it does not grant access to a blocked site.

## 8. Read the outcome

| Outcome | Action |
| --- | --- |
| `DOWNLOADED` | Check the PDF and version; the file passed download checks |
| `SKIPPED_ALREADY_IN_DEST` | Matching filename with a PDF header and sufficient size is already present |
| `SKIPPED_ALREADY_IN_ZOTERO` | Enable inclusion of attached references if you also want a separate download |
| `OA_BLOCKED_MANUAL` | Use a verified author copy or normal browser access |
| `DOWNLOAD_FAILED` | Inspect errors; retry later or supply a verified alternate URL |
| `PAYWALLED_OR_OA_NOT_FOUND` | Check identifiers and search for another copy; this does not establish a paywall |
| `WEB_RESOURCE` | Open the retained documentation/dataset link |
| `WITHDRAWN` | Read the source withdrawal notice before using the work |
| `ERROR` | Inspect the recorded exception and correct the input or filesystem problem |

Retry a batch report with:

```powershell
python main.py --retry-report "previous_report.csv" --dest-folder "D:\Research\Papers"
```

Add `--retry-not-found` to include no-copy-found rows. A CLI run can finish with exit code zero while individual references remain unresolved; use the CSV statuses to assess the batch.

## 9. Other publisher and repository helpers

| Source | Supported handling |
| --- | --- |
| IEEE Xplore | Article IDs, stamp viewers, normal PDF routes, and OA repository fallbacks |
| Wiley | PDF/direct-PDF forms; old DOI semicolon suffixes are retained |
| Springer | Article-to-PDF URL forms |
| Frontiers / MDPI | Article PDF forms and article metadata |
| arXiv | Identifier/title discovery, PDF forms, and withdrawal notices during landing-page resolution |
| HAL | Repository record-to-document routes |
| OpenReview / IACR | Forum/abstract-to-PDF forms |
| Author / institutional pages | PDF metadata, repository controls, matching-title links, and same-host PDF.js viewers |

These helpers use normal public endpoints and do not bypass sign-ins, CAPTCHAs, or site access controls.

## 10. Optional API credentials and maintenance

For sustained discovery, optional `OPENALEX_API_KEY` and `SEMANTIC_SCHOLAR_API_KEY` environment variables can help with authenticated service budgets. They do not provide ACM publisher access. Restart the server after setting them. See [OpenAlex authentication](https://help.openalex.org/api/authentication/), [Semantic Scholar's API](https://api.semanticscholar.org/api-docs/snippets), and [ACM open access](https://www.acm.org/publications/openaccess).

Maintainer helper locations:

| File | Purpose |
| --- | --- |
| `paperharbor/single_paper.py` | DOI/URL input and bibliographic metadata |
| `paperharbor/diagnose.py` | Read-only candidate inspection |
| `paperharbor/providers/acm.py` | General ACM candidate routes |
| `paperharbor/providers/author_copies.json` | Small reviewed source catalog with evidence pages and dates |
| `paperharbor/providers/matching.py` | Identifier normalization and identity checks |
| `paperharbor/providers/landing.py` | Publisher, repository, and viewer resolution |
| `paperharbor/http_helpers.py` | Numeric and HTTP-date Retry-After parsing |
| `paperharbor/downloader.py` | Streaming, retries, redirect checks, and PDF-header validation |

Catalog additions require a matching DOI/title and a verified author/conference/institutional source. Avoid slide decks and unrelated papers. Restart after changing the catalog so cached entries are reloaded.

Run the regression suite from the repository root:

```powershell
python -m unittest discover -s tests -v
```

Mocked tests establish helper behavior, not current availability of every publisher. Use the diagnostic helper and a real download to verify the paper you need.
