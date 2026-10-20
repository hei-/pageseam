# PageSeam

**Turn PDFs, Word files and scans into clean Markdown, searchable PDF or Word — on CPU, on your own server.**

English | [简体中文](README.zh-CN.md)

Works with PDF, Word (doc / docx), PowerPoint and images; the Markdown is made for knowledge bases and LLMs. PageSeam decides page by page whether OCR is needed: text pages keep their original text untouched, while scanned pages, garbled pages and embedded images go through PaddleOCR. **Tables that span pages are stitched back into one table.** Files never leave your server.

- **Scans**: only the pages that need OCR get it; slightly skewed scans are straightened automatically. Cell accuracy on scanned tables is 98.4% (see [TESTING.md](TESTING.md#current-baseline-full-evaluation-8-core-cpu)).
- **Tables**: merged cells are kept (as HTML tables); cross-page tables are merged, repeated headers removed, and rows split by a page break joined back together.
- **Built for knowledge bases**: every page starts with a `<!-- page N -->` marker so retrieval results can cite page numbers; headers, footers and page numbers are removed so they don't become a noise chunk on every page.
- **Integrations**: REST API and an upload page; a [Dify plugin](dify-plugin/README.md) (workflows and knowledge pipelines); a [WeKnora parser engine](integrations/weknora/README.md).

| Input | Handling |
|-------|----------|
| PDF | Classified page by page, see "Page classification" |
| Word (doc, docx, rtf, odt, wps), PowerPoint (ppt, pptx, odp) | Converted to PDF with LibreOffice, then the same pipeline: native text becomes the text layer without OCR; **embedded scans and screenshots are recognized** |
| Images (png, jpg, tif, webp, bmp) | Full-page OCR at the original resolution (no upscaling); one page per frame for multi-page TIFF; phone photos are rotated according to EXIF |

Excel is not supported: converting a spreadsheet to PDF paginates it by print area and breaks the table structure. A row-based Excel parser does a better job.

## Quick start

Requires Docker and at least 8 GB of memory (2 worker processes by default, about 2.8 GB each).

```bash
echo "PAGESEAM_API_KEYS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" > .env
docker compose up -d --build      # first build takes ~15 min: ~4.2 GB image, incl. ~600 MB of OCR models downloaded at build time
```

Upload page at `http://localhost:8000/` (enter the API key from `.env`), API docs at `/docs`. No internet access is needed at runtime.

Build arguments:

| Argument | Description |
|----------|-------------|
| `APT_MIRROR` | Debian mirror host, e.g. `mirrors.aliyun.com` or `mirrors.cloud.tencent.com` in mainland China |
| `PIP_INDEX` | PyPI index, default `https://pypi.org/simple/`; e.g. `https://mirrors.aliyun.com/pypi/simple/` in mainland China |
| `PADDLE_PACKAGE`, `PADDLE_INDEX` | PaddlePaddle package and index; for GPU see "GPU deployment" |
| `CONSTRAINTS` | Version lock file, default `constraints.txt`: every Python package, including indirect dependencies, is pinned so builds are reproducible. To upgrade dependencies, edit `requirements.txt` and run `scripts/update-constraints.sh` |
| `OCR_LAYOUT_MODEL`, `OCR_DET_MODEL`, `OCR_REC_MODEL`, `OCR_TABLE_MODEL` | Models downloaded at build time; must match the runtime environment variables of the same name |

```bash
docker compose build --build-arg APT_MIRROR=mirrors.aliyun.com --build-arg PIP_INDEX=https://mirrors.aliyun.com/pypi/simple/
```

### Kubernetes

The image works as is. Keep in mind:

- **Run exactly 1 replica** with the `Recreate` strategy: job state lives in process memory, and this also avoids two copies of the models in memory during updates.
- Use `emptyDir` for `/data` (uploads and results) and `/tmp`, together with `readOnlyRootFilesystem: true` and `runAsNonRoot: true` (the image runs as UID 10001).
- Memory requests 3Gi, limits 7Gi (2 workers); use `GET /health` for liveness and readiness probes.
- Inject `API_KEYS` from a Secret.

## Configuration

Everything is set through environment variables (see [`config.py`](docparser/config.py)):

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEYS` | (required) | Comma-separated keys, for rotation; each key only sees its own jobs |
| `MAX_WORKERS` | 2 | Concurrent jobs. Each worker loads its own copy of the models, ~2.8 GB |
| `OCR_THREADS` | 2 | CPU threads per job |
| `MAX_QUEUE` | 20 | Queue limit; beyond it the API returns 429 |
| `MAX_FILE_MB` / `MAX_PAGES` | 100 / 300 | Size and page limits per file |
| `JOB_TTL_MINUTES` | 60 | How long results are kept before automatic deletion |
| `OCR_DPI` | 200 | Render resolution for scanned pages; raise it for small print |
| `OCR_DESKEW` / `OCR_DESKEW_MAX` | 1 / 5 | Deskew on/off and maximum angle |
| `OCR_DEVICE` | cpu | `cpu`, or `gpu` / `gpu:0` (requires the GPU image) |
| `OCR_*_MODEL` | see above | Model combination, see "Choosing OCR models" |
| `CLASSIFY_*` | see "Page classification" | Page classification thresholds |
| `CONVERT_TIMEOUT` | 300 | LibreOffice conversion timeout (seconds) |
| `DEFAULT_LANGUAGE` | en | Language of error messages, progress and page reports (`en` / `zh`) when the request has no `Accept-Language` |

## Outputs

| Output | Description | Best for |
|--------|-------------|----------|
| **Searchable PDF** | Original pages untouched down to the pixel, with an invisible text layer placed where OCR found text | Must look exactly like the original, yet be selectable, copyable and searchable |
| **Word** | Text and mixed pages via pdf2docx (layout preserved); OCR pages rebuilt from layout blocks (headings, paragraphs, tables, stamps / images); merged in original page order, one section per page with the original paper size and orientation. Scanned tables and text screenshots inside mixed pages become editable content by default (see below) | Editing the content |
| **Markdown** | Each page starts with `<!-- page N -->`; tables stay HTML (to express merged cells); headers, footers and page numbers are dropped (for text pages, lines repeated across pages, see below); radical code points mapped back to common characters | Knowledge bases, LLM input |

### Images inside mixed pages (`word_images`)

How images embedded in text pages (scanned tables, attachment screenshots) are handled in Word output:

| Value | Handling |
|-------|----------|
| `replace` (default) | If a table or text (at least 10 characters) is recognized in the image, it is replaced in place with an editable Word table and paragraphs; photos, logos and diagrams without text are kept |
| `keep` | All kept as images; looks like the original, but text in images is not editable |
| `both` | Keep the image and append the recognized tables and paragraphs below it |

How it works: before pdf2docx runs, images containing text are cut out of a temporary copy and replaced by a placeholder; after conversion the placeholder paragraph is replaced with the recognized content. The rest of the page still uses the original text and layout.

## Cross-page tables

In Markdown, a table that spans pages is merged into one table on its starting page, preceded by `<!-- table pages 3-5 -->` (also recorded in the job result's `summary.cross_page_tables`).

Rule: the last block of page N is a table (page-number lines ignored), the first block of page N+1 is also a table, and either

- the column counts match (scans, Word tables without a repeated header row), or
- the first row of the table on page N+1 equals the header (Word's "Repeat header row", scans with the header printed on every page); the repeated header is removed when merging.

Word tables "allow row to break across pages" by default, so long text in a row is cut in two: if the first row of the continuation has an empty first column and the same column count as the previous row, it is joined back to the last row of the previous page. The same happens within a page: the wrapped lower half of a cell is recognized as its own row (like `|||M12||||`); rows with an empty first column and more than half of the cells empty are joined to the row above.

When page N+1 holds nothing but this table after merging, page N+2 is checked too, so one table can span many pages. Markdown tables from text pages and HTML tables from scanned pages can also be merged (the result is HTML).

When the Dify plugin produces `chunks`, a cross-page table becomes its own chunk labeled with its page range ("第 3–5 页"); very long tables are split by rows and every chunk repeats the header.

> Not handled: text between the two parts of a table (they are no longer treated as one table); tables without ruling lines that are only aligned by spacing (not detected as tables on text pages). Rows whose first column is genuinely empty are treated as broken rows and joined to the row above.

**Word output** keeps the original pagination by default (`word_tables=keep`): one table per page, easy to compare with the original, and a wrong guess never glues two tables together. To edit the whole table (add rows, sort, totals), use `word_tables=merge`: when the last table of one page and the first table of the next are separated only by empty paragraphs, page numbers and section breaks, and have the same column count or header, they are merged into one table, the repeated header removed, broken rows joined, and the header marked as "Repeat header row" (Word repeats it on every page). If both pages have the same paper size, the section break between them is removed as well and the table flows across pages. The searchable PDF always matches the original.

## Page classification

Four metrics are read per page (PDF structure only, milliseconds), matched in order:

| Verdict | Condition | Handling |
|---------|-----------|----------|
| Scanned page | Fewer than 20 visible characters, images cover more than 50% | Full-page OCR |
| Scanned page (old OCR layer) | As above, plus hidden text (render mode 3) | Old text layer removed, then OCR again (its quality is unknown; for Chinese it is usually worse than PaddleOCR) |
| Text converted to outlines | No text, but many vector paths | Full-page OCR |
| Blank page | No text and no images | Skipped |
| Garbled page | Valid character ratio below 90%, or an Identity-H font without a ToUnicode map | Full-page OCR |
| Mixed page | Text is fine, but a single image covers more than 10% of the page | Original text kept, OCR only on image regions |
| Text page | None of the above | No OCR |

Every conversion returns a per-page report (verdict, reason, time). If classification gets it wrong, use `ocr=force` (OCR everything), `ocr=off` (no OCR) or `ocr_pages=3,5-8` (specific pages). Thresholds can be tuned with `CLASSIFY_<NAME>` environment variables (see [`config.py`](docparser/config.py)).

## API

Everything except `/health` and the upload page requires `Authorization: Bearer <API key>`. Each key only sees its own jobs. Error messages, progress and page reports are in English or Chinese according to `Accept-Language` (e.g. `-H "Accept-Language: zh-CN"`); a job keeps the language it was submitted with. The upload page has a language switch.

```bash
# Submit (asynchronous, returns job_id immediately)
curl -H "Authorization: Bearer $KEY" -F file=@contract.pdf -F outputs=docx,pdf,markdown http://localhost:8000/v1/jobs
# Progress and per-page report
curl -H "Authorization: Bearer $KEY" http://localhost:8000/v1/jobs/<job_id>
# Download (kind: docx / pdf / markdown), then delete; otherwise it is cleaned up after 60 minutes
curl -H "Authorization: Bearer $KEY" -OJ http://localhost:8000/v1/jobs/<job_id>/files/docx
curl -H "Authorization: Bearer $KEY" -X DELETE http://localhost:8000/v1/jobs/<job_id>
```

| Parameter | Description |
|-----------|-------------|
| `file` | PDF, Word (doc, docx, rtf, odt, wps), PowerPoint (ppt, pptx, odp) or image (png, jpg, tif, webp, bmp). One page per image (one per frame for multi-page TIFF); Office files are converted to PDF first; returns 400 if the file signature doesn't match the extension |
| `outputs` | Comma-separated: `docx`, `pdf`, `markdown`; default `markdown` |
| `ocr` | `auto` (default) / `force` / `off` |
| `ocr_pages` | Extra pages to OCR in full, e.g. `3,5-8` |
| `pages` | Only process these pages, e.g. `1-10` |
| `word_images` | Images inside mixed pages in Word output: `replace` (default) / `keep` / `both`, see above |
| `word_tables` | Cross-page tables in Word output: `keep` (default) matches the original pagination / `merge` joins them into one table, see "Cross-page tables" |

When queued jobs exceed `MAX_QUEUE` the API returns 429 (with `Retry-After`). Password-protected PDFs return 400.

## Performance and resources

Measured on an 8-core CPU without GPU (10-page sample, 7 pages need OCR). Timings in the model table use 4 threads:

| Metric | Value |
|--------|-------|
| Text pages | Under 1 s / page |
| OCR pages | ~5–8 s / page (`OCR_THREADS=2`; 3–6 s with 4 threads) |
| Whole sample | 40–60 s (~56 s for all three outputs) |
| Word → PDF | ~2–3 s (3-page sample; LibreOffice starts fresh each time) |
| Memory | ~5 GB total (2 workers, each with its own models) |

By default 2 jobs run concurrently (`MAX_WORKERS=2`) with 2 CPU threads each; the container is limited to 4 cores / 7 GB (`docker-compose.yml`).

## Choosing OCR models (measured)

| Configuration | Per page | Memory | Result |
|---------------|----------|--------|--------|
| PP-StructureV3 defaults (PP-DocLayout_plus-L + server detection) | 42 s | 8 GB | Unusable on CPU |
| All lightweight models (PP-DocLayout-S + mobile recognition) | 3 s | 2 GB | Loses body text, tables treated as images |
| **PP-DocLayout-M + mobile detection + server recognition + SLANet_plus** | **3–6 s** | **2.8 GB** | **Used** |

Original text from text pages is cleaned up too ([`markdown.py`](docparser/markdown.py)):

- **Headers and footers**: short text within the first or last two blocks of a page that repeats on more than half of the pages is removed, even if the page number differs ("Internal — page 3"). Only page-number-shaped digits are normalized, so body text like "Subtotal 300" is never removed; headings and tables are kept. Removed lines are listed in the job summary's `running_lines`. Otherwise every page gets a chunk containing only the header, which jumps to the top of retrieval results whenever a question mentions the manual's title.
- **Radical code points**: some PDF fonts map characters like 车 and 用 to identical-looking code points in Kangxi Radicals (U+2F00–2FD5) or CJK Radicals Supplement (U+2E80–2EF3). They look right but can't be searched. Kangxi Radicals are mapped back with NFKC; Radicals Supplement characters are mapped from a table, only when they stand alone as characters. CJK Compatibility Ideographs (U+F900–FAFF, e.g. 率 mapped to U+F9DB) are mapped back with NFC.
- **Merged cells**: in tables generated by pymupdf4llm, vertically merged cells appear only in the first row and the following rows are empty; when text is vertically centered across two rows, the low hyphen glyph lands in the next row ("SP-200" becomes "SP200", "-15 ℃" loses its minus sign); two-row headers ("Output power" over "Rated" / "Peak") get scrambled. Tables with merged cells are rebuilt from the cell structure of `find_tables` (derived from ruling lines): text is taken word by word, a vertically merged value is filled into every row it covers, multi-row headers are joined as "Output power/Rated", and horizontally merged data cells keep the value only in the first column. Tall cells in continuation tables that pymupdf4llm splits into several rows by line spacing (row count differs from `find_tables`) are rebuilt the same way. Other tables are left alone.

Additions on top of PP-StructureV3 ([`ocr.py`](docparser/ocr.py)):

- **Table orientation classification disabled**: it mistakes wide, short tables for rotated ones, transposing the whole table and reversing rows and columns.
- **Missed regions recovered**: PP-StructureV3 drops the text in regions the layout model missed. Those recognized lines are regrouped into paragraphs by position and inserted back into the reading order.
- **Deskew**: before OCR the skew angle is estimated by projection (within ±5°, ~0.1–0.3 s per page), the page is straightened and recognized, and coordinates are mapped back to the original, so the searchable PDF's text layer still lines up. A scanned table skewed by just 0.6° already misaligns cells. PaddleOCR's own UVDoc is not used: it is slow on CPU and its non-linear warp can't be mapped back to the original coordinates. `OCR_DESKEW=0` turns it off.
- **Table cells refilled**: recognized lines are reassigned to cells by coordinates. When text from two adjacent cells is recognized as one line, splitting it by position tends to cut one or two characters off, so such single-line cells are cropped and recognized individually; cells still empty are recognized once more on their own (single digits and "—" are easily missed by the detection model). Cells containing nothing but one horizontal stroke become "—".
- **Images at native resolution**: uploaded images are recognized at their original pixel size. pymupdf sizes the page at 96 DPI by default, so rendering at 200 DPI would upscale by more than 2×, and the table model misaligns entire tables on oversized images.
- **Page orientation**: pages scanned sideways or upside down are rotated upright and coordinates mapped back; pages with `/Rotate` are handled in their display orientation.
- **Font size**: estimated as line width ÷ character count; recognition boxes include padding, so estimating from height overshoots.
- **Text normalization**: full-width commas inside numbers (`353，370.00`) become half-width; list items merged by the layout model (`…。2.…`) are split.

## Known limitations

- **Word is converted to PDF before parsing**: layout follows LibreOffice's rendering, so page breaks may differ slightly from Word; Chinese fonts like SimSun and SimHei are replaced with Noto CJK, which doesn't affect the text. When a docx has CJK body text but en-US as its default East Asian language (English Word templates, files generated by python-docx), the language is switched to that of the body text before conversion: otherwise LibreOffice renders curly quotes “” in a Western font, the quotes become separate lines in the text layer and get moved to the end of the sentence. The original file is untouched; only the copy used for conversion is changed. Heading levels come from PDF bookmarks (Word's Heading 1/2/3 styles are exported as bookmarks); documents without heading styles are judged by font size.
- **LibreOffice processes untrusted files**: macros are never run, but externally linked images in a document may be downloaded. That's acceptable for internal users; restrict the container's outbound network before exposing it publicly.
- **OCR pages are re-laid out in Word**: text, tables and stamps are all there, but fonts and line spacing differ from the original. Use the searchable PDF when it must match the original exactly.
- **Images replaced with editable content in mixed pages are re-laid out from the recognition result**: the height the image occupied is not kept, so the following content moves up. Use `word_images=keep` or the searchable PDF to match the original.
- **OCR makes mistakes**: e.g. in the sample "0.5‰" is recognized as "0.5%。" and "X 轴" as "×轴". Double-check amounts, account numbers and other critical figures against the original. Cell accuracy on scanned tables is in [TESTING.md](TESTING.md#current-baseline-full-evaluation-8-core-cpu).
- **Merged cells in scanned tables**: cells spanning several columns (like a "Total" row) may get the wrong structure, and the refill step is skipped for that table.
- **PowerPoint**: speaker notes are not output (LibreOffice doesn't export notes to PDF); several bullets in one text box may be merged into one line, without losing text.
- **Job state lives in memory**: unfinished jobs are lost when the container restarts; clients just resubmit. That's why only a single replica is supported.
- **PaddlePaddle pinned to 3.2.2**: 3.3.x fails on CPU (oneDNN) when running PP-StructureV3 with `ConvertPirAttribute2RuntimeAttribute not support`.

## GPU deployment

Code and image support GPU, but it hasn't been tested on a GPU yet.

```bash
docker build -t pageseam:gpu \
  --build-arg PADDLE_PACKAGE=paddlepaddle-gpu==3.2.2 \
  --build-arg PADDLE_INDEX=https://www.paddlepaddle.org.cn/packages/stable/cu126/ .
```

- **Image**: the CUDA runtime comes with the pip package; the base image is unchanged.
- **Runtime**: `OCR_DEVICE=gpu:0`, and the container needs GPU access (`docker run --gpus 1`, or `nvidia.com/gpu: 1` on Kubernetes).
- **Models**: on GPU you can switch to more accurate models that are too slow on CPU, such as layout `PP-DocLayout_plus-L` and detection `PP-OCRv5_server_det`. Build arguments and runtime environment variables share the same names, so build and runtime use the same models.
- **Concurrency**: `MAX_WORKERS` can be raised on GPU. Each worker loads its own copy of the models, so size it by GPU memory.

## Testing

Test procedure, the one-command test script and pass criteria for each level are in [TESTING.md](TESTING.md):

```bash
docker build -t pageseam .
./scripts/run-tests.sh                 # unit tests + end-to-end checks + scanned-table cell evaluation (quick)
./scripts/run-tests.sh tables --full   # full table evaluation
```

Tests run inside the service image; you only need Docker and python3. All samples are generated by scripts; put generated samples and your own files in `tests/samples/` (git-ignored) for manual checks on the upload page.

## Layout

```
├── Dockerfile               # LibreOffice + CJK fonts; OCR models downloaded at build time; CPU / GPU PaddlePaddle chosen by build args
├── docker-compose.yml       # Single-host deployment
├── requirements.txt         # Direct dependencies
├── constraints.txt          # Locked versions of every Python package
├── docparser/
│   ├── main.py              # FastAPI: auth, job API, upload page
│   ├── jobs.py              # Job queue: long-lived workers (models loaded once), progress, expiry
│   ├── pipeline.py          # One job: (Office → PDF) → classify → OCR → three outputs
│   ├── convert.py           # LibreOffice: doc, docx, ppt etc. → PDF, file signature checks; images → PDF
│   ├── classify.py          # Per-page OCR decision
│   ├── ocr.py               # PP-StructureV3 wrapper and additions (deskew, table refill)
│   ├── searchable_pdf.py    # Invisible text layer
│   ├── word.py              # pdf2docx + OCR page layout + section merging
│   ├── markdown.py          # Markdown output, cross-page table merging, headings from bookmarks
│   └── static/index.html    # Upload page
├── scripts/
│   ├── download_models.py
│   ├── update-constraints.sh  # Regenerate constraints.txt
│   ├── security-check.sh    # Secrets, dependency vulnerabilities, code, Dockerfile, image
│   └── run-tests.sh         # One-command tests (run in the service image)
├── tests/                   # Unit tests, sample generators, end-to-end checks, table cell evaluation
├── dify-plugin/             # Dify plugin (MIT)
├── integrations/weknora/    # WeKnora parser engine bridge (MIT)
├── TESTING.md               # Test guide
└── THIRD_PARTY_NOTICES.md   # Third-party licenses
```

## License

[AGPL-3.0](LICENSE). The core dependencies of the PyMuPDF family are dual-licensed under AGPL-3.0 / Artifex commercial license, so this service is AGPL as well: **if you offer the service to others over a network (including SaaS), you must make the complete source, including your changes, available to those users**. If you don't want to release your source, buy a commercial PyMuPDF license from Artifex. Licenses of all dependencies are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

`dify-plugin/` and `integrations/weknora/` only talk to the service over HTTP and are released separately under MIT.
