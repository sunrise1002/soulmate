# Development scripts

Canonical commands live in the root pyproject and package.json. Add cross-platform
helper scripts here only when needed.

`validate_contribution.py` is the single executable policy for commit messages,
branch names, and pull-request titles. Local Git hooks and GitHub Actions invoke
the same implementation so their behavior cannot drift. Keep it standard-library
only and update its unit tests with every policy change.

`key_embedding_spike.py` reproduces the key consistency P0 measurements: it scores
one ONNX embedding model against the packaged key retrieval dataset and prints
recall, antonym similarity, latency, and peak memory. It needs `onnxruntime`,
`tokenizers`, and `numpy`, which are intentionally not workspace dependencies, so
run it from a throwaway environment as described in its module docstring and in
the [P0 spike report](../docs/phases/key-consistency-p0-spike-report.md). It never
downloads a model itself.
