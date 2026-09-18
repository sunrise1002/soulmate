# Decision evaluation

Run the packaged synthetic benchmark with:

```sh
uv run --locked soulmate evaluate
```

The command compares deterministic random, frozen LLM-only, memory-only, Personal
Model, and sequential Decision Model baselines. It reports Top-1 and Top-2
accuracy, log loss, multiclass Brier score, and top-label expected calibration
error with populated confidence bins. The frozen LLM-only probabilities are test
inputs; evaluation never calls a provider or the network.

Pass `--dataset PATH` to use another validated JSON dataset. Decisions are
evaluated in file order so only earlier choices train the online pairwise model.
Committed datasets must remain synthetic or pseudonymous and must not contain
owner data.

## Key retrieval

`soulmate_core.evaluation.key_retrieval` measures whether a similarity function
puts the right existing target key inside the 50-key budget that
`select_known_keys` shares with an extraction provider, and how close opposite
keys such as `ui.theme.dark` and `ui.theme.light` sit. The packaged
`synthetic-key-retrieval-v1` dataset mixes Vietnamese and English messages against
English dotted keys with Vietnamese owner labels.

Tests run with `uv run --locked pytest tests/evaluation` and use only the built-in
word-overlap baseline and fake scorers, so they need no model and no network.
`scripts/key_embedding_spike.py` runs the same harness against a real ONNX model
outside the test suite; see the
[P0 spike report](../../docs/phases/key-consistency-p0-spike-report.md).
