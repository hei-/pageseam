# PageSeam document parser plugin

English | [Simplified Chinese](readme/README_zh_Hans.md)

Source code: https://github.com/hei-/pageseam

Parse PDF, Word (doc, docx), PowerPoint and images with your self-hosted [PageSeam](https://github.com/hei-/pageseam) service. It decides page by page whether OCR is needed and outputs Markdown for knowledge bases, searchable PDF or Word. Scans embedded in Word files are recognized, and tables spanning pages are merged into one.

**You need a running PageSeam service** (Docker, runs on CPU). The plugin only uploads files and fetches results; files are sent only to the service URL you configure, never to third parties.

## Tools

| Tool | Output |
|------|--------|
| **Parse document to Markdown** (`parse_document`) | `text`: Markdown, each page starting with `<!-- page N -->`<br>`chunks`: knowledge base chunks, ready for the Knowledge Base node |
| **PDF to Word / searchable PDF** (`convert_document`) | `files`: Word and / or searchable PDF |
| **Get job result** (`get_job_result`) | Fetch a result by `job_id` when one of the tools above timed out |

`chunks` is split by page instead of by separators: every chunk starts with the document name, page and section; tables are kept whole or split by rows with the header repeated; cross-page tables become one chunk. In a knowledge pipeline, connect `chunks` directly to the Knowledge Base node.

## Credentials

| Field | Description |
|-------|-------------|
| Service URL | E.g. `http://<server IP>:8000`. Must be reachable from Dify's `plugin_daemon` container — use the host's LAN IP, not `localhost` |
| API Key | The service's API key |

## Installation

Package it with the [Dify plugin CLI](https://docs.dify.ai/en/develop-plugin/getting-started/getting-started-dify-plugin) (`dify plugin package ./dify-plugin`) and upload it under "Plugins → Install plugin → Local package". Locally packaged plugins must be signed, see [GUIDE.md](https://github.com/hei-/pageseam/blob/main/dify-plugin/GUIDE.md#signing).

Chunking rules, signing and development notes: [GUIDE.md](https://github.com/hei-/pageseam/blob/main/dify-plugin/GUIDE.md).

## License

[MIT](https://github.com/hei-/pageseam/blob/main/dify-plugin/LICENSE). The PageSeam service is AGPL-3.0.
