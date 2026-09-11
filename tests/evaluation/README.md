# Decision evaluation

Run the packaged synthetic benchmark with:

```sh
uv run --locked decision-twin evaluate
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
