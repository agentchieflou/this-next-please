# Desktop Bridge transcript, Power BI Desktop 2.157 (August 2026)

Built from the contract Microsoft Learn documents for the Desktop Bridge
(<https://learn.microsoft.com/power-bi/developer/agentic/power-bi-desktop-bridge-overview>): the four
methods `bridge.manifest`, `application.state.get/v1`, `file.reload/v1` and
`report.snapshot.capture/v1`, their parameters, and their result fields. The descriptions are the
documentation's; the file path and page are a fixture's, and the snapshot is a 2x1 white PNG.

It is the drift baseline `ad-pbip bridge probe` compares a live manifest with (the newest version
directory wins). Replace it with a recorded one on the laptop -- `ad-pbip bridge record --pid <pid>
--page <page id>` writes `tests/fixtures/bridge/<Desktop version>/transcript.jsonl` -- and keep this
README's first paragraph only if the recording matches it.

`2.138.1452.0/` is the pre-release bridge (`manifest`, `status`, `reload`, `screenshot`), kept so
the legacy dialect stays tested.
