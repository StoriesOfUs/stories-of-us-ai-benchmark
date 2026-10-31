# Self-contained evidence benchmark V01

This isolated experiment compares the original DeBERTa NLI premise with an automatically prepared premise. The preparer can only select and concatenate existing verified, public-safe evidence passages. It does not generate facts or insert the tested claim into the evidence.

Conditions:

- A: original evidence baseline.
- B: deterministic automatic preparation.
- C: human-prepared diagnostic evidence for the seven historical cases only; never counted as automatic performance.

The model revision, label mapping, 512-token limit, entailment threshold (0.5) and entailment margin (0.3) are fixed from the preceding experiment. Atomic claims remain manually inventoried; automatic extraction from a complete summary is not implemented.

Outputs are experimental, not editorial approval and not for publication.
