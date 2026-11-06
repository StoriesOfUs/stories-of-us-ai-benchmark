# Offline validation

Preparation validation is separate from checker accuracy.

The actual proposed workflow passed:

- Ruby/Psych YAML parsing;
- `actionlint 1.7.12` with exit 0;
- Python syntax compilation using an isolated bytecode cache.

The package's standard-library offline suite covers:

- freeze verification and absence of live authority;
- all 4 development / 10-claim and 12 evaluation / 29-claim memberships;
- approved AAPD correction;
- identical evidence/claim inclusion and answer-key leakage checks;
- conservative complete-input bounds (largest HHEM 726 and MiniCheck 654 UTF-8-byte-based units, versus the 1,024-token cap; these are not exact token counts);
- development threshold pass/fail paths and reject-everything failure;
- fail-closed aggregation and invalid result handling;
- exact 90-computation and zero-retry accounting;
- exact 36-wheel CPU lock and model-file allowlists;
- isolated mock locked/approved/repeat-refused authority states;
- candidate subprocess isolation, development gating and local-only loading;
- inode-aware regular/hard/symlink accounting;
- manual-only, read-only, 45-minute workflow controls.

Exact tokenizer counts require the pinned tokenizer files and therefore remain a mandatory future execution preflight. No model-loading or performance conclusion follows from these offline checks.
