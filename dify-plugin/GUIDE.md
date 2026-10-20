# PageSeam plugin guide

English | [简体中文](GUIDE.zh-CN.md)

Details behind the [plugin README](README.md): chunking rules, signing, development notes. Not included in the plugin package.

## `chunks`: why not the general chunker

Dify's built-in General Chunker only splits on separators and never merges short paragraphs: page markers become chunks of their own, body chunks carry no page number, and the content ends up fragmented (the 10-page sample is cut into 63 chunks).

`chunks` splits by page with these rules:

- Paragraphs are merged up to the maximum chunk length (default 800); a heading starts a new chunk; chunks never cross pages.
- Tables become plain text in `| cell | cell |` form. HTML tags would eat into the keyword quota of the economical index.
- Tables are chunked by the maximum table length (`table_max_chars`, default 0, meaning the same as the maximum chunk length): a table within the limit goes into one chunk whole; a longer table is split by rows, **each chunk carrying the header**, so any retrieved chunk explains its columns.
- When questions often need the whole table (totals, how many items), set the maximum table length to 2000–3000: small and medium tables stay in one chunk, very large ones are still split by rows, so chunk length always has a limit. Values below the maximum chunk length are treated as the maximum chunk length.
- Cross-page tables (already merged by the service) become their own chunk labeled with their page range, e.g. "【合同 · 第 1–2 页】".
- Each chunk starts with "【document name · 第 N 页 · section】". The document name is the file name without extension: knowledge base retrieval gives the model only the chunk content, not the file name, so without it the model can't tell which chunk came from which version of a manual or which of several similar contracts. Turn off "Label chunks with document name" (`chunk_doc_name`) if you don't need it.

The sample is cut into 15 chunks, and any retrieved chunk can cite its page. In a knowledge pipeline, connect `chunks` directly to the "Knowledge Base" node (`index_chunk_variable_selector: [parse node, chunks]`).

## Signing

By default Dify only installs plugins signed by the Marketplace (`FORCE_VERIFYING_SIGNATURE=true`). Two ways to install a locally packaged plugin:

- **Sign with your own key (recommended)**: generate a key pair with `dify signature generate -f mykey`, sign with `dify signature sign dify-plugin.difypkg -p mykey.private.pem -c community` (category community, never posing as an official category); put the public key in a directory the plugin daemon can read, set `THIRD_PARTY_SIGNATURE_VERIFICATION_ENABLED=true` and `THIRD_PARTY_SIGNATURE_VERIFICATION_PUBLIC_KEYS=<public key path>`, and recreate the `plugin_daemon` container. Never commit the private key.
- Disable verification (`FORCE_VERIFYING_SIGNATURE=false`): every unsigned plugin can be installed; only for test environments.

> Put the public key file in place before enabling third-party signature verification. If the file is missing, verification fails in the daemon and **no plugin at all** (official ones included) can be installed.

## Development notes

- **Only one `Tool` subclass per tool file**: the SDK looks up `Tool` subclasses in the module namespace. `from utils.tool_base import DocParserTool` pulls the base class into the namespace too, and the plugin fails at startup with `Multiple subclasses of Tool`. Write `from utils import tool_base` and subclass `tool_base.DocParserTool` instead.
- **Every parameter needs a `human_description`**: missing it on a single parameter makes the plugin fail at startup with `Error loading tool configuration`.
- **To upgrade after code changes, just package and upload again**: the version number can stay the same; when the package content changes, its unique identifier (checksum) changes, and configured credentials are kept.

## Layout

```
dify-plugin/
├── manifest.yaml
├── main.py                    # 600 s limit per invocation
├── provider/pageseam.{yaml,py}   # Credentials and validation
├── tools/                     # The three tools
├── utils/
│   ├── client.py              # Submit, poll (from 2 s, up to 10 s between polls), 429 retry, download, delete
│   ├── tool_base.py           # Read parameters, output results; delete the job on the service right after fetching
│   └── chunking.py            # Chunking by page
├── readme/README_zh_Hans.md   # Chinese README (shown on the Marketplace for Simplified Chinese users)
└── tests/test_chunking.py     # Unit tests for chunking rules (not packaged)
```

Run the unit tests after changing chunking rules (standard library only):

```bash
cd dify-plugin && python3 -m unittest discover tests
```
