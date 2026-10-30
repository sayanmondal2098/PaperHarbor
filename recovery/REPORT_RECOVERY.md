# Report recovery — 30 October 2026

Audited report: `D:\CyberHull\Referances\paperharbor_report_20261030_214538.csv`.

The report contains 27 references: 4 downloaded, 10 already in the destination, 6 download failures, 3 manual-access cases, and 4 with no open copy located.

## Recovered files

Six PDFs were downloaded successfully to **`D:\CyberHull\Referances\Recovered_20261030`**. Five resolve failed/manual entries; one corrects an unrelated-file download. Existing PDFs and the original report were retained.

| Paper | Original outcome | Source used | Downloaded bytes |
| --- | --- | --- | --- |
| The Quickhull algorithm for convex hulls | Open manually | [WIAS-hosted manuscript](https://www.wias-berlin.de/people/si/course/files/Barber96-quickhull.pdf) | 11,308,471 |
| Understanding bag-of-words model: a statistical framework | Download failed | [Authors' LAMDA laboratory copy](https://www.lamda.nju.edu.cn/publication/ijmlc10.pdf) | 248,570 |
| A graph-theoretic approach for the detection of phishing webpages | Download failed | [Charles Darwin University repository](https://researchers.cdu.edu.au/files/34079517/33300082.pdf) | 1,259,826 |
| Approximate polytope ensemble for one-class classification | Download failed | [University of Barcelona accepted manuscript](https://diposit.ub.edu/items/8ff6b48f-9857-4676-84c2-334ea21dfecd) | 1,280,288 |
| An Entropy-Based Network Anomaly Detection Method | Open manually | [Publisher-hosted PDF](https://mdpi-res.com/d_attachment/entropy/entropy-17-02367/article_deploy/entropy-17-02367-v2.pdf?version=1429602828) | 1,435,793 |
| Dataset of suspicious phishing URL detection | Originally marked downloaded, but from an unrelated APWG report URL | [Correct Frontiers article PDF](https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2024.1308634/pdf) | 1,650,855 |

The downloader checked PDF headers and sizes. Titles/authors were checked against the source pages or indexed documents during research; the app does not perform automatic semantic verification of PDF contents. Some copies are author or accepted manuscripts rather than the publisher's final layout.

The recovery download report is `paperharbor_report_20261030_215330.csv` inside the recovery folder. A subsequent expanded retry of the nine original failed/manual entries is recorded in `paperharbor_report_20261030_215424.csv`; it skipped the five recovered PDFs and retained diagnostics for the other four.

## Four entries still unresolved

| Paper | Observed issue | Next step |
| --- | --- | --- |
| Use of the Mann-Whitney U-test for clustered data | Wiley PDF routes returned HTTP 403. The original URL conversion also dropped the semicolon suffix of its old-style DOI; that conversion is now fixed. | Open the [DOI page](https://doi.org/10.1002/(sici)1097-0258(19990615)18:11%3C1387::aid-sim126%3E3.0.co;2-v) in a browser; use institutional access or request a copy from the authors/library if needed. |
| A Network Model to Study the Underlying Characteristics of Phishing Sites | The article landing route returned HTTP 202 without a PDF. No verified alternate manuscript was found in this audit. | Try the [publisher page](https://doi.org/10.1109/LNET.2023.3347724) through your library or request an author manuscript. A 202 response does not establish a paywall. |
| Web phishing detection techniques: a survey on the state-of-the-art, taxonomy and future directions | Metadata indicated an OA location, but Wiley/IET PDF routes returned HTTP 403. | Open the [IET/Wiley article page](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/iet-net.2020.0078) interactively and use its PDF control. |
| IDS-Twin: Digital Twin-Based Intrusion Detection Systems for Wireless Networks | Crossref supplied an IEEE accepted-manuscript URL, but it returned HTML instead of PDF content. No verified external author copy was found. | Open the [IEEE article](https://ieeexplore.ieee.org/document/11152540) in a browser; use normal publisher/library access or contact an author. |

Semantic Scholar returned HTTP 429 during the expanded retry. Its unavailable results mean this audit cannot establish that no other open copies exist. The four references with no open copy located also remain unverified; check their titles, authors, and missing DOIs before retrying them.

## Retry from the app

1. Restart `python web.py`.
2. Choose **Upload bibliography / retry report** and upload the original `.csv` report. Failed/manual/error rows load by default; optionally include “No open copy found.”
3. Use **Select all** or select individual references.
4. Expand **Use another PDF link** beneath a reference to paste a verified author/repository PDF URL.
5. Choose the destination and start downloading.
6. Expand **Attempt details** for each unsuccessful result. The result also provides publisher/search links, a suggested filename, and a next action.
7. After a job, **Retry failed / manual entries** retries those outcomes without processing successful or skipped papers.

If downloading in your browser, save the PDF into your destination using the suggested filename. A later normal run skips a matching file with a PDF header and size greater than 1,024 bytes. Check identity/version first.

## Retry from the command line

From the repository root:

```powershell
python main.py --retry-report "D:\CyberHull\Referances\paperharbor_report_20261030_214538.csv" --dest-folder "D:\CyberHull\Referances\Recovered_20261030" --pdf-overrides recovery/verified_pdf_overrides.json
```

Add `--retry-not-found` to include the report's “No open copy found” rows. The [override file](verified_pdf_overrides.json) maps DOIs to researched source URLs; these links can change and are not built into the provider code.

To download the corrected Frontiers article into the original destination, select that reference, supply its verified URL, and enable **Download again if a matching file exists**. PaperHarbor preserves the old file and gives the corrected download a numeric suffix. Replace or rename files only after checking their contents.

## Optional provider credentials

The expanded retry exposed Semantic Scholar rate limiting. PaperHarbor now accepts optional credentials via environment variables, scoped to each provider's own host:

```powershell
$env:OPENALEX_API_KEY = "YOUR_OPENALEX_KEY"
$env:SEMANTIC_SCHOLAR_API_KEY = "YOUR_SEMANTIC_SCHOLAR_KEY"
python web.py
```

Restart the server after setting variables. A key does not grant publisher access or guarantee a download. OpenAlex describes its free keys and budgets in [Authentication](https://help.openalex.org/api/authentication/); Semantic Scholar documents its `x-api-key` header in the [Academic Graph API](https://api.semanticscholar.org/api-docs/snippets). Never commit real keys.
