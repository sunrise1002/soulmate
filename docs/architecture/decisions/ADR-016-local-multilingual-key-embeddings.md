# ADR-016: Local multilingual key embeddings behind an embedding port

Status: Accepted for the key consistency increment on 2026-09-18 (step P0).
Implementation follows in steps P4 and P5. ADR-014 remains reserved for the
planned Phase 13 trusted-provenance decision.

## Context

Target keys are free-form dotted English identifiers, while the owner writes in
Vietnamese. Step A shares known keys with the extraction provider and ranks them
by word overlap, which cannot bridge languages. The
[P0 spike](../../phases/key-consistency-p0-spike-report.md) measured that baseline
on a synthetic 168-key personal model: word overlap places the correct key inside
the 50-key budget for 62.5% of English messages but only 27.3% of Vietnamese ones.
Keys that are never shared are the keys an extraction invents again under a new
name, which is the duplication this increment exists to stop.

Normalized merging (step P1 to P3) only catches keys that differ in spelling.
Bridging languages needs a semantic signal, and the product must stay local-first:
`privacy.mode` defaults to `strict_local`, where `EgressPolicy` denies every
non-loopback endpoint.

## Decision

Introduce an `EmbeddingProvider` port in the kernel with a `NullEmbedding` default
and a `LocalOnnxEmbedding` adapter running `onnxruntime`, `tokenizers`, and
`numpy` entirely on the device. No embedding is computed, and no dependency is
loaded, until the owner enables the feature.

The default artifact is **`bge-m3` int8** (`Xenova/bge-m3`, `onnx/model_int8.onnx`,
MIT, 568 MB), confirmed by the owner on 2026-09-18 after the P0 measurements. The
spike also measured `bge-m3` fp16, `multilingual-e5-base` O4, and
`multilingual-e5-large` fp32; all four reach at least 97.6% recall inside the
50-key budget, so the deciding factors were cost and antonym behavior. `bge-m3`
int8 is the smallest and fastest artifact that keeps opposite keys measurably
apart, and the `multilingual-e5` int8 exports are AVX-512 VNNI builds that cannot
run on arm64 at all.

Acquisition is an explicit owner action. The artifact URL and SHA-256 are pinned
in the product, the download is requested only when the owner presses the download
button, and the egress policy permits it as a named `model_artifact` download even
in `strict_local` mode. Downloads are resumable and verified before activation,
partial files are removed on failure, manual file import remains an offline
fallback, and `offline` mode refuses the download entirely. Any load failure falls
back to step A behavior rather than degrading the product.

Embeddings are computed inside the existing background learning job and stored in
`target_key_embeddings` with their `model_id` and `text_hash`, so chat latency is
unchanged and a model change invalidates and recomputes vectors. Similarity adds a
score to `select_known_keys`; brute-force search with `numpy` is sufficient at the
expected key counts and `sqlite-vec` stays deferred.

Semantic similarity may only ever produce a `suggested` alias for owner review.
The spike measured that every opposite key pair in the dataset is more similar to
its opposite than the median correct message-to-key match is, under every model
tested, so no threshold can separate "the same concept" from "the opposite
concept". This confirms owner decision 3 as a permanent rule, not a cautious
default.

## Consequences

An owner who never presses the download button keeps today's behavior, today's
install size, and no new network activity. An owner who enables embeddings gains
cross-language key reuse — Vietnamese recall inside the 50-key budget rises from
27.3% to 97.7%, and to 100% once owner-edited labels exist — at the cost of a
568 MB artifact, roughly 11 ms per text on macOS arm64, and about 1.8 GB peak
resident memory while the model is loaded, which forces lazy loading and release
after idle.

Because the artifact is pinned by URL and SHA-256, a withdrawn or re-uploaded
upstream file is a verification failure rather than a silent substitution; the
pin must be updated deliberately. Vectors are derived data: they are excluded from
portable exports, included in local backups, and rebuildable at any time.

Model artifacts live in `DATA_DIR/models`, which `ARCHIVE_DIRECTORIES` currently
includes under a 512 MB cap; step P4 must exclude or relocate them before the
first artifact can be stored, or every backup fails.

Windows, Linux, and x64 behavior is unverified: the spike ran only on macOS arm64.
Step P6 owns the packaged cross-platform smoke test, and the fallback to step A
exists precisely because a native runtime may fail to load there.

## Verification (step P6, 2026-09-18)

The pinned artifact was downloaded and run for the first time on macOS arm64.
Both SHA-256 pins matched the published files byte for byte, and the recorded
sizes were replaced with the exact ones (568,456,694 and 17,082,821 bytes). The
`bge-m3` int8 export pools inside the graph, so `_OnnxSession` returns its output
directly; vectors are 1024-dimensional and L2-normalized, a warm single text costs
about 8–9 ms, and the P0 retrieval harness reproduced its numbers against the real
model (97.7% Vietnamese recall inside the 50-key budget without labels, 100% with
them, and 6 of 27 opposite pairs still above the 0.85 review threshold).

Two facts recorded above were corrected by that first real run:

- Peak resident memory is about 1.9 GB, not 1.8 GB. The owner-facing estimate is
  now 2.0 GB so the dialog never understates it.
- Every `onnxruntime` exception derives directly from `Exception`, not from
  `RuntimeError`. The adapter's failure handling was widened accordingly;
  narrowing it would have let a corrupt model file escape as an unhandled error
  instead of falling back to the lexical ranking this ADR relies on.

The runtimes are packaged as the optional `soulmate-daemon[embeddings]` extra, so
a plain install stays unchanged while the desktop sidecar bundles them.
`tokenizers` pulls `huggingface-hub` transitively; the product never imports it
and loads the tokenizer from the verified local file only, so no second download
path exists.
