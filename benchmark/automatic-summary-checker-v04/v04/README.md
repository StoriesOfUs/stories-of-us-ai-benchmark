# Stories Of Us automatic summary checker test package V04

Status: **PREPARATION PASS / EXECUTION LOCKED / CHECKER RELIABILITY NOT TESTED**

V04 is the narrow scoring-contract successor to frozen V03. It preserves V03's
model-facing checker and Gemma inputs, 15 development cases, 12 hidden evaluation
cases, 81 protected meaning units, evidence, expected verdicts, thresholds, model
settings and proposed resources.

The protected post-response adjudication now distinguishes `MAPPED`, `INVENTED`,
`INVENTORY_GAP` and `UNCERTAIN_MAPPING`. A returned compound claim may have more
than one semantic portion, so a mapped portion cannot hide an invented or
unresolved portion. Inventory gaps and uncertain mappings remain explicit and
block the affected gate without becoming checker inventions or factual errors.

The maximum proposed schedule remains 35 requests across three gated UTC days,
zero probes/retries, 498,000 input tokens, 48,640 output/reasoning tokens,
17,665.317664 reserved neurons, a 17,666-neuron hard cap and £0 expenditure.

There is no live authority, state, ledger, output or consumed request slot. Start
with `reports/05_governance_handover.md`; the exact freeze is recorded in
`reports/06_freeze_receipt.md`.

