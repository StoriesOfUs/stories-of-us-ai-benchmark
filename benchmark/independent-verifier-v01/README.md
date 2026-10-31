# Independent evidence verifier V01

This is a public-safe, manual-only benchmark for `cross-encoder/nli-deberta-v3-small`.

It compares manually inventoried atomic claims with the smallest relevant verified evidence passages. The evidence is the NLI **premise** and the claim is the **hypothesis**. The benchmark confirms the model's actual label order from its pinned configuration:

1. contradiction;
2. entailment;
3. neutral.

`neutral` means the evidence does not establish the claim. It is never treated as permission to publish. An entailment prediction is also not editorial approval.

The benchmark contains:

- known Qwen false-PASS claims used for development diagnosis;
- known supported controls used to prevent a reject-everything result;
- a frozen balanced holdout of supported, unsupported and contradicted claims.

Only the two development groups calibrate the conservative entailment threshold and margin. Holdout predictions are evaluated after calibration. Evidence pairs above the model's 512-token input limit are not truncated and return review required.

Three deterministic inference passes are retained. Automatic claim extraction is not implemented; the manually verified atomic inventory prevents omitted subclaims from being mistaken for complete verification in this experiment.

The GitHub workflow is `workflow_dispatch` only, uses read-only repository permissions, downloads the pinned model temporarily, deletes it before artifact upload and retains public-safe results for seven days.

Status labels:

- `SUPPORTED`
- `NOT_ESTABLISHED`
- `CONTRADICTED`
- `REQUIRES_EDITORIAL_REVIEW`

All results are experimental, not editorially approved and not for publication. Operational readiness remains not authorised.
