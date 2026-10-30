# Domain and ACM audit — report 215039

Input: `D:\CyberHull\Referances\paperharbor_report_20261030_215039.csv`.

The original report has **26 references**: 13 downloaded, 7 with no open copy found, 4 download failures, and 2 manual-access cases. The 13 unresolved rows include duplicate PhishStorm references, three web resources, and a withdrawn arXiv record.

## Five PDFs recovered

Files were saved to **`D:\CyberHull\Referances\Recovered_215039`**, preserving the original files and report:

| Paper | Working source | Bytes |
| --- | --- | --- |
| Structural Balance: A Generalization of Heider's Theory | [Stanford course copy](https://snap.stanford.edu/class/cs224w-readings/cartwright56balance.pdf) | 1,221,915 |
| Practical Secure Aggregation for Privacy-Preserving Machine Learning | [ACM CCS conference copy](https://acmccs.github.io/papers/p1175-bonawitzA.pdf) | 1,772,025 |
| Beyond Blacklists: Learning to Detect Malicious Web Sites from Suspicious URLs | [Author's UCSD copy](https://cseweb.ucsd.edu/~jtma/papers/beyondbl-kdd2009.pdf) | 179,558 |
| Sunrise to Sunset: Analyzing the End-to-End Life Cycle and Effectiveness of Phishing Attacks at Scale | [USENIX paper](https://www.usenix.org/system/files/sec20-oest-sunrise.pdf) | 3,382,952 |
| PhishStorm: Detecting Phishing With Streaming Analytics | [HAL institutional repository copy](https://inria.hal.science/hal-01092771/document) | 2,452,916 |

The downloaded copies passed PDF-header and size checks. Source pages/indexed documents were checked for matching paper titles and authors. Manuscript versions may differ; the application does not perform full semantic verification of PDF contents.

The first download audit is `paperharbor_report_20261030_220431.csv`. The subsequent application verification is `paperharbor_report_20261030_220945.csv`, covering nine selected rows: one new PhishStorm download, two existing-file skips (including the duplicate PhishStorm entry), three web resources, one withdrawn work, one blocked ACM paper, and one failed IEEE download.

`recovery_summary.csv` combines both passes for all 13 originally unresolved rows: five downloaded, one duplicate skipped, three web resources, one withdrawn record, two failed downloads, and one manual-access case. This summary retains the initial successful Sunrise download rather than relabeling it as its later existing-file skip.

## Domain fixes

- **ACM Digital Library:** a dedicated provider recognizes `10.1145/...` DOIs and `dl.acm.org` article URLs, tries PDF/ePDF routes, and retains normal article links. Legacy citation URLs can be resolved when metadata/redirects are accessible.
- **Crossref:** ACM PDF URLs marked `content-type: unspecified` are no longer discarded. Exact normalized-title discovery is available when a DOI is missing.
- **Identity checks:** the original secure-aggregation reference has DOI `10.1145/3133956.3133982`. Its reported manual link incorrectly led to `10.1145/3625343.3625344`, a different work titled “Practical and Efficient Secure Aggregation…”. DOI conflicts in candidates, redirects, article metadata, and title-search results are now rejected.
- **HAL / ORBilu / repository pages:** HAL `/document` routes, normal repository download controls, and same-host PDF.js viewers are recognized. The old browser-impersonation user agent produced HTML at the HAL endpoint during testing; a truthful PaperHarbor user agent retrieved its PDF.
- **IEEE:** article/stamp viewer URLs can yield the normal `stampPDF/getPDF.jsp` route. A route returning HTML is still rejected rather than saved as a PDF.
- **OpenReview and IACR:** forum/abstract URLs have normal PDF-route variants; access controls still require manual follow-up when present.
- **Timeouts and duplicates:** TCP connection attempts are capped at 10 seconds while read timeout remains configurable internally (30 seconds by default). Repeated DOI failures in one run reuse their first outcome; attachment skips are not reused for unattached references.

ACM research is available through its open-access publishing program, but this does not guarantee that every automated client can retrieve every PDF. The ACM endpoints tested here returned HTTP 403. See [ACM open access](https://www.acm.org/publications/openaccess) and the [ACM conference explanation of the 2026 transition](https://ht.acm.org/ht2026/open-calls/submission-instructions/open-access-publishing-at-acm/).

## Three entries are web resources

These are retained as `WEB_RESOURCE`, with direct links and a clear explanation rather than a paywall/no-PDF failure:

- [Flower secure aggregation documentation](https://flower.ai/docs/examples/flower-secure-aggregation.html).
- [Apache Kafka KRaft documentation](https://kafka.apache.org/41/operations/kraft/).
- [UCI PhiUSIIL dataset](https://archive.ics.uci.edu/dataset/967/phiusiil+phishing+url+website+dataset).

The old CSV omitted their source URLs. A corrected CSL-JSON file, `retry_references.json`, is saved in the recovery folder with researched source URLs. New reports preserve `Original_URL` and `Item_Type` to avoid losing this context on later retries. No dataset archive was downloaded or treated as a research PDF.

## The temporal signed-GNN work is withdrawn

[arXiv:2605.26290](https://arxiv.org/abs/2605.26290) explicitly marks the work withdrawn and says the simulation results are incorrect and could mislead readers. The current PDF route returns HTTP 404. PaperHarbor now records `WITHDRAWN` when it encounters this notice during page resolution, preserves the explanation, and stops further recovery for that reference. It does not silently substitute an earlier version. Review the source notice before using or citing this work.

## Three unique papers remain unresolved

| Paper | Evidence from this run | Next step |
| --- | --- | --- |
| Federated Learning For Cyber Security: SOC Collaboration For Malicious URL Detection | [ORBilu record](https://orbilu.uni.lu/handle/10993/44927) identifies a PDF, but the repository host timed out; IEEE routes returned HTML. | Retry the repository later or request an author copy. The [source PDF link](https://orbilu.uni.lu/bitstream/10993/44927/1/PID6431211.pdf) is retained in the override file. |
| POSTER—CAIRN: Causal Active Inference for Real-Time Cyber Attack Diagnosis and Response | ACM metadata was found; [the ACM PDF](https://dl.acm.org/doi/pdf/10.1145/3779208.3804893) returned HTTP 403. | Open the [ACM article](https://dl.acm.org/doi/10.1145/3779208.3804893) in a browser. The [author's project page](https://sayanmondal2098.github.io/research/cairn.html) identifies the publication but did not expose a public PDF in this audit. |
| Adaptive Malicious URL Detection: Learning in the Presence of Concept Drifts | Publisher/staging and normal IEEE viewer-derived links returned HTML. No verified downloadable author copy was found. | Open the [DOI page](https://doi.org/10.1109/TrustCom/BigDataSE.2018.00107), use normal library access, or request an author manuscript. |

Some metadata requests also returned HTTP 429; this audit therefore cannot establish that no other accessible copies exist.

## Reproduce

From the repository root:

```powershell
python main.py --export-file "D:\CyberHull\Referances\Recovered_215039\retry_references.json" --dest-folder "D:\CyberHull\Referances\Recovered_215039" --pdf-overrides recovery/domain_report_overrides.json
```

Alternatively restart `python web.py`, upload that CSL-JSON file, select references, and use the alternate-link field for verified repository URLs. The [override JSON](domain_report_overrides.json) contains researched URLs, including unresolved sources; its presence is not a guarantee that a URL currently downloads. The temporal paper's URL is retained for diagnosis, and the application stops upon finding its withdrawal notice.
