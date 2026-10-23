# Release Audit and Verification Record

## Original Release Review: 2026-10-14 to 2026-10-15

Dates use Asia/Shanghai. The observations below describe the original release and are not an assurance that every check was rerun for later documentation changes.

### Security Review

The development repository's reachable branches and tags were scanned: 36 commits and 297 historical file objects, including deleted files. Checks covered credential filenames, private keys, common provider tokens, credential assignments, contact information and absolute paths. DOCX/XLSX XML was inspected inside archives. No matching real credential exposure was identified; `.env`, `secrets.toml`, `.venv` and `.runtime` were not found in the reviewed history. Pattern scanning cannot guarantee detection of every possible secret.

Findings and disposition:

- An upstream experimental workbook contained machine paths in metadata; development logs contained local paths.
- Two upstream videos were approximately 14.8 MB and 26.5 MB and were unnecessary for the automotive application.
- Food-supply experiments, videos, DOCX files, upstream report PDFs, old CSV outputs and development records were excluded from the public snapshot.
- Numeric matches in video binaries were not treated as evidence of real contact details; the videos were excluded entirely.
- No original history was rewritten and no force push was used. An allowlisted application snapshot with independent history retained the MIT license, original copyright, upstream attribution and a SHA-256 manifest.
- `.gitignore` was expanded to cover credential-file variants, databases, validation environments and test outputs.

The simulated components, suppliers, orders, production lines, demands, qualifications and costs are identified as fictional. No enterprise connection or actual purchasing interface exists.

### Runtime and Safety Boundaries

- `app.py` defaults to local mode. `public_app.py` fixes public mode before importing workflow modules and disables model tracing.
- Public mode blocks model clients and assistant calls. Explicit model-report requests return a template fallback.
- Inventory, templates, Excel/CSV imports, dynamic planning, mitigation and PDF work without Ollama.
- Inputs, drafts, results and conversations use `st.session_state`, with no shared user-data cache, checkpoint store or database. Two separate AppTest sessions checked input and chat isolation.
- Uploads are parsed in memory, never executed or saved to the repository. Limits include 5 MB inputs, 25 MB total XLSX decompression and 200 archive entries. Macros and external workbook links are rejected; text, columns, SKU counts and planning rows are bounded.
- Public pages do not show internal tracebacks. Internal exception logging is limited to exception types.
- Project-relative paths remove dependence on Windows desktop paths. PDF generation uses ReportLab's Chinese CID font declaration, not the developer's local font files.

### Original Local Verification

| Check | Recorded result |
|---|---|
| Environment | Fresh CPython 3.11.9 virtual environment |
| Dependencies | Actual installation from requirements; lockfile generated; package imports and `pip check` passed |
| Final full local regression | 202 tests passed, no failures, 99.378 seconds after online link and screenshot checks |
| Initial public-mode tests | 13 passed: model blocking, fallback, PDF, upload boundaries, archive limits, isolation, CSV header preflight, release allowlist and screenshots |
| Workflow portability | Three tests passed after removing dependence on old Git commits |
| Browser interactions | Single SKU, 12-item batch, 30-day plan, order results and mitigation controls exercised |
| PDF | Generated and actually downloaded; not inferred from a button's presence |
| Excel/CSV | Generation, parsing, validation and result checks exercised by modules and AppTest; online evidence recorded separately below |
| Real local AI | Existing `llama3.2:latest` answered a fictional delay question in 11.06 seconds; no model download or paid API |
| Desktop launchers | Script tests passed; existing uncommitted launcher changes excluded; no claim of a new shortcut double-click test |
| Linux packages | All 72 locked packages resolved and downloaded as CPython 3.11 Linux wheels; this alone was not runtime proof |
| Initial Ubuntu CI | 201 tests executed, five Windows-only skips, no failures |

The first restricted-environment full run stalled on Windows socket handling; execution with local sockets permitted completed. A legacy Excel template initially conflicted with upload validation; template round-trip and full regression passed after the fix.

A pre-release scan of 80 candidate files found no provider-token, private-key, local-user-path or personal-email matches. Template creator metadata was `openpyxl`; the largest candidate was approximately 60 KB at that stage. The 80-file application snapshot plus manifest was approximately 0.8 MB and independently passed 200 tests in 80.856 seconds without the original development history. Four later online captures brought the release allowlist to 84 application files. These are historical counts, not the current manifest's count.

Three existing, uncommitted launcher-related files were preserved outside release commits; the snapshot used their committed versions. Local public-mode captures were `public-single.jpg`, `public-batch.jpg` and `public-planning.jpg`. The four `online-*.jpg` captures came from actual cloud interaction.

## Initial GitHub and Online Acceptance: 2026-10-15

- Repository: https://github.com/youxing-han/AutoSupply-Copilot ; API confirmed Public and push succeeded.
- Application: https://autosupply-copilot.streamlit.app/ ; Community Cloud, Python 3.11, `public_app.py`.
- Initial Ubuntu run: https://github.com/youxing-han/AutoSupply-Copilot/actions/runs/38668565677 ; 201 tests, five skips, zero failures, 61.575 seconds; `pip check` passed.
- A fresh HTTP session without pre-existing cookies or authorization reached both the root and application frame with status 200 and no sign-in redirect.
- Single SKU: changing stock from 800 to 160 and rerunning produced two days of coverage, a five-day coverage gap and 640 reference replenishment units.
- Batch: 12 demo items completed without failures; a five-item XLSX and a fictional CSV with the distinct identifier `CLOUD-CSV-TEST` produced five and one successful analyses respectively.
- Planning: the default 12-item, 30-day plan ran. An uploaded five-sheet, five-SKU, 14-day delay workbook produced a first sensor shortage on 2026-10-22, 80 unmet units and 260 closing units. Its original-date reference had zero unmet demand and 180 closing units; 500 confirmed receipt units and pending orders were shown separately.
- Mitigation: backup supply plus internal transfer left zero unmet demand at CNY 2,980. A late low-price option left 80 unmet units; expediting cost CNY 6,000. No real procurement took place.
- AI: the public app displayed the unavailable-local-Ollama notice while templates, facts and analysis remained available.
- Session separation: changing stock to 160 in one tab did not change another new tab's default 800 or expose the first tab's uploaded draft.
- PDF: the actual online single-SKU PDF was 4,205 bytes and one page. Text extraction found Chinese text, SEN-001 and stock 800. Poppler rendering showed no clipping, overlap or missing pages. It substituted a local Chinese font; compatibility with every PDF reader was not verified.
- Excel: the actual cloud-generated workbook was 6,251 bytes, 12 rows, 14 columns and 12 unique SKUs. Reuploading the downloaded file and running analysis produced 12 results, six high-risk items and no failures.

Browser automation initially failed to capture downloads through the outer cloud iframe. Retrying on the native application page produced actual downloaded files; the initial timeout was not counted as download success.

## Documentation and Screenshot Refresh: 2026-10-23

The README gallery was replaced by four fresh local public-mode browser captures. The 12-component delay plan, HRN-006 detail, original-date reference and mitigation comparison were actually operated. Data, captions and reproduction steps are recorded in `SCREENSHOTS.md`. The English documentation preserves the fictional-data, deterministic-calculation, local-AI and business-model boundaries.

This refresh does not constitute a new full cloud acceptance, real-model run, concurrency test or download verification. Its checks cover public documentation, screenshot assets and public release behavior; current test and push results belong to the corresponding commit and Actions run.

The refreshed development checkout passed 205 tests in 111.204 seconds, with no failures. The 16-test public-release suite also passed, including an automated reproduction of the gallery's component counts, shortage quantities, reference inventory and mitigation costs. The 91 candidate application files were scanned again, with no credential, private-key, personal-machine-path or private-contact pattern matches. Historical image files remain available but are no longer displayed in the README gallery.

## Attribution and Remaining Limits

The original Cindy Aprilia MIT copyright remains in `LICENSE`; dependency notices are in `THIRD_PARTY_NOTICES.md`. Installed license metadata and package license files were reviewed. Transitive dependencies include MIT, BSD, Apache, PSF and MPL licenses; library distributions retain their notices and are not bundled into this source snapshot. Build-environment setuptools is not shipped. This records the review scope, not a legal opinion.

No concurrency stress test or professional penetration test was performed. Free cloud availability and sleep behavior depend on the platform. There is no enterprise-data validation, forecast-accuracy guarantee, realized savings claim or support for sensitive business data.
