# Local Notes Connector

This reference Phase 11 connector reads `.md`, `.markdown`, and `.txt` files below
one owner-selected directory. It performs no network calls, requests no
credentials, follows no symbolic links, and emits sensitive `RawEvent` source
material. Unchanged content is idempotent across synchronizations.

Configure it through the owner-only Connections API or desktop screen. A sync is
bounded to 1,000 files, 1 MiB per file, and 20 MiB total.
