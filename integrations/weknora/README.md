# WeKnora integration: PageSeam as the parser engine

English | [简体中文](README.zh-CN.md)

[WeKnora](https://github.com/Tencent/WeKnora)'s built-in PDF parser does no OCR (scanned pages depend on a vision model) and doesn't recognize table structure. `bridge.py` plugs PageSeam in as a WeKnora parser engine: scanned pages go through PaddleOCR, table structure is kept, cross-page tables are merged into one, and headers, footers and page numbers are removed.

**WeKnora stays untouched**: no changes to its code, images or configuration files. The bridge uses WeKnora's built-in "self-hosted MinerU engine" interface (tested with v0.8.3).

```
Upload → WeKnora (knowledge base rule set to mineru)
           → GET /v1/health returns 404, legacy protocol chosen → POST /file_parse
             → parser-bridge (WeKnora's internal network, no published port) → PageSeam (submit job, wait, fetch Markdown)
         ← Markdown + content_list split on <!-- page N --> (WeKnora uses it for source locations)
WeKnora chunks → embeds → indexes as usual
```

| File | Purpose |
| --- | --- |
| `bridge.py` | The bridge, Python standard library only; also answers `/docs` (WeKnora's connectivity check) and `/health` |
| `docker-compose.override.yml` | Starts parser-bridge together with WeKnora, attached only to `WeKnora-network`, limited to 0.5 CPU / 256M |
| `configure_parser_engine.py` | Sets the workspace's MinerU endpoint to `http://parser-bridge:8080` (`PUT /tenants/kv/parser-engine-config`); does nothing if already set |

## Deployment

1. Deploy PageSeam (see the [main README](../../README.md#quick-start)) and note its URL and API key. The URL must be reachable from WeKnora's containers, e.g. `http://<host LAN IP>:8000`.
2. In WeKnora's deployment directory:
   ```bash
   mkdir -p parser-bridge && cp <this repo>/integrations/weknora/bridge.py parser-bridge/
   cp <this repo>/integrations/weknora/docker-compose.override.yml .
   ```
3. Add to WeKnora's `.env`:
   ```bash
   PAGESEAM_URL=http://<host LAN IP>:8000
   PAGESEAM_API_KEY=<PageSeam API key>
   SSRF_WHITELIST=<existing value>,parser-bridge   # otherwise WeKnora refuses to call internal containers
   ```
4. Start: `docker compose -f docker-compose.yml -f docker-compose.override.yml up -d`
5. Register the engine: in WeKnora's web UI, set the MinerU endpoint in the parser engine settings to `http://parser-bridge:8080`, or run
   ```bash
   WEKNORA_BASE=http://127.0.0.1:8080 WEKNORA_EMAIL=<admin> WEKNORA_PASSWORD=<password> \
     python3 configure_parser_engine.py
   ```

The API key lives only in parser-bridge; WeKnora itself never needs it.

## Enabling it per knowledge base

Registering the MinerU endpoint only adds an optional engine. **Each knowledge base chooses for itself**; those that don't keep using the built-in parser:

- Web UI: knowledge base settings → parsing → choose "MinerU" for pdf, docx and doc;
- API: when creating or updating a knowledge base, set `chunking_config.parser_engine_rules` to
  `[{"file_types": ["pdf", "docx", "doc"], "engine": "mineru"}]`.

To turn it off, remove the rule (or set it back to builtin). Documents already ingested must be re-parsed to switch back.

## Comparison

Three generated samples were ingested with the built-in parser and with PageSeam; hybrid search + rerank, top 5, looking only at source chunks:

| Question (capability) | Built-in parser | PageSeam |
| --- | --- | --- |
| Cross-page table on text pages | Rank 1 | Rank 1 |
| Cross-page table on **scanned pages** | Missed: scanned pages have no text | Rank 1 |
| Table spanning 3 pages, continuation without header | Rank 3 | Rank 1 |
| Skewed scanned image (converted to PDF before upload) | Missed | Rank 1 |

- Chunks: when WeKnora splits a PageSeam table into several chunks, each repeats the header; HTML tables from scanned pages are converted to Markdown tables. Every chunk carries its source location (page number).
- Time: 21–41 s per file (8-core CPU, mostly OCR). WeKnora waits for MinerU up to 1000 s by default; parser-bridge itself waits at most 950 s (`BRIDGE_TIMEOUT`).

## Limitations

- **Images can't be uploaded directly**: WeKnora requires a vision model already at upload time ("上传图片文件需要设置 VLM 模型"), before any parser engine is chosen. Convert the image to a single-page PDF first and it goes through PageSeam.
- **Chunks from cross-page tables are attributed to the starting page**: once PageSeam merges a cross-page table it no longer knows which page each row came from, so the whole table is recorded on its starting page.
- **Excel doesn't go through PageSeam**: PageSeam doesn't support Excel; xlsx/xls keep using WeKnora's built-in parser.
- **Load**: PageSeam processes 2 jobs at a time by default; when its queue is full (429) parser-bridge waits and retries.
- **"Failed to load model list" in the frontend after rebuilding WeKnora**: unrelated to this integration. WeKnora's frontend nginx resolves the backend address only at startup; after the backend container is recreated, run `docker compose restart frontend`.

## License

This directory is released under [MIT](LICENSE).
