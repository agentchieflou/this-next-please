# Azure AI Content Understanding — what the service is, and what it actually requires

Read when a call fails, when a result is not the shape you expected, or before changing
`agentdata/connectors/content_understanding.py`.

## Naming

Microsoft is mid-rebrand from **Azure AI Foundry** to **Microsoft Foundry**. The PyPI distribution
is `azure-ai-contentunderstanding`, the import is `azure.ai.contentunderstanding`, and the portal
may say either name. All of these refer to the same resource. Neither name is a typo.

## What it does

An **analyzer** is a field schema plus a base model, authored in the portal. You send it a
document; it returns the document's content (text, layout, markdown) and one entry per declared
field, each with a value, a confidence, and a **span** — an offset and length back into that
content. There is no way to define fields from this CLI: the analyzer is the schema, and creating
one is a portal task.

Two analyzer shapes matter here:

| Shape | `analyzers get` shows | Use for |
|---|---|---|
| content-only (e.g. `prebuilt-documentAnalyzer`) | `fields: 0` | text and layout only |
| field-extracting | `fields: N` with a schema table | `ad-dpm extract-fields` |

Pointing field extraction at a content-only analyzer returns no fields at all — which reads like an
empty document. `ad-foundry analyzers get` before a batch is how you avoid that.

## Configuration

| Setting | Config path | Environment | AGENTS.md fact |
|---|---|---|---|
| endpoint | `content_understanding.endpoint` | `CONTENT_UNDERSTANDING_ENDPOINT` | `content_understanding_endpoint` |
| analyzer | `content_understanding.analyzer` | `CONTENT_UNDERSTANDING_ANALYZER` | `content_understanding_analyzer` |
| auth mode | `content_understanding.auth` | — | `content_understanding_auth` |

Precedence is flag → environment → config → AGENTS.md, the same as every other connector.

The **endpoint is the resource host and nothing more** — `https://<resource>.services.ai.azure.com`.
The SDK appends its own path, so an endpoint with `/contentunderstanding` on the end produces a 404
that reads like a missing analyzer. `ad-doctor` checks the shape offline and says which mistake it
looks like; the one it catches most often is a portal *key* pasted where the endpoint goes.

### Auth

`entra` (the default) uses `DefaultAzureCredential` — the same `az login` the Power BI step already
needs, so an operator who can reach a workspace can reach this with nothing new to rotate. Nothing
is stored.

`key` reads the resource key from the keyring under `content_understanding:default`, user
`resource-key` — the same place and shape as a data source's password. `CONTENT_UNDERSTANDING_KEY`
overrides it for one session. **The key never goes in config**; `config.assert_no_secrets` refuses
to store one.

## The SDK, checked against the published wheel

Written against `azure-ai-contentunderstanding` **1.1.0**, api-version `2025-11-01`:

```
ContentUnderstandingClient(endpoint, credential)   # credential: AzureKeyCredential | TokenCredential
  .begin_analyze(analyzer_id, *, inputs=[AnalysisInput(url=...)], string_encoding=...)  -> LROPoller
  .begin_analyze_binary(analyzer_id, binary_input=b"...", *, string_encoding=..., content_type=...)
  .get_analyzer(analyzer_id) / .list_analyzers()
```

Two keywords are **required and undocumented as such**. Both were found by reading the wheel, and
both fail only at the first real request:

- **`string_encoding`** on both analyze calls. `codePoint` is the value this connector sends: it is
  the service default and the only one whose spans line up with Python string indices. `utf16`
  would be right for a .NET caller and would silently misplace every offset here.
- **`content_type`** on `begin_analyze_binary`. The operation does `kwargs.pop("content_type")`
  with no default, so omitting it raises `KeyError` rather than sending a sensible header. The
  connector guesses it from the filename and falls back to `application/octet-stream`.

## The result shape

```json
{"analyzerId": "...", "apiVersion": "...", "warnings": [],
 "contents": [{"kind": "document", "mimeType": "application/pdf", "path": "page-1",
               "markdown": "...",
               "fields": {"<FieldName>": {"type": "number", "valueNumber": 125000.0,
                                          "confidence": 0.94,
                                          "spans": [{"offset": 60, "length": 10}]}}}]}
```

The value key is `value` + the type: `valueString`, `valueNumber`, `valueDate`, and so on. The
connector reads it **by that prefix rather than from a list of known types**, so a field type Azure
adds later yields its value instead of silently reading as empty — which would be indexed as "the
document does not contain this".

`fields_from_result()` flattens this to one row per field carrying `value`, `type`, `confidence`,
`content_index`, `content_path`, `mime_type`, `offset`, `length`, sorted by field name so two runs
over the same document diff cleanly. It takes the plain JSON shape, which is what the SDK
deserialises **and** what a recorded fixture holds — so the mapping is testable without Azure,
without credentials and without the optional package installed. The fixtures are in
`tests/fixtures/content_understanding/`; `ad-foundry analyze --out <path>` is how you record a new
one.

## Inside `ad-dpm extract-fields`

`--engine azure-content-understanding` registers as an `Engine` in `agentdata/dpm/extract.py`. Same
schema in, same rows out, same statuses — nothing downstream knows which engine ran.

- **The job schema's `hint` is unused.** The analyzer holds the schema. A `not_found` detail
  therefore names the fields the analyzer actually returned, so a schema mismatch is legible on the
  first row instead of after somebody re-checks a hundred documents by hand.
- **One request per document, not per field.** `extract()` calls the engine once per field with the
  same text; the analysis is cached on that text.
- **`needs_ocr_review` is decided before the engine is called.** OCR-routed documents never reach
  the service, so they are never billed for and never extracted from.
- **A service failure raises `content_understanding_failed`, never `not_found`.** A service that
  could not be reached has said nothing about the document.
- **Below `--min-confidence` (default 0.7) a value is `ambiguous`, not `found`** — the same meaning
  it has for the simple engine: a reviewer has to look.

## Installing

```
pip install "agentdata[content-understanding]"
```

Optional like `teradata` and `oracle`: most installs never call the service, and `azure-identity`
pulls a large dependency tree of its own. Every import of the SDK is deferred, so the connector,
the engine and `ad-doctor` all work with the package absent — they say so instead of failing on an
import.
