# Reuse and static compatibility

## Proven dependency environment

The package copies byte-for-byte the successful smoke test's complete 36-wheel Python 3.12/Linux x86_64 lock and expected-version inventory. Every wheel is an exact URL with a full SHA-256. Installation remains `--no-deps --no-index --only-binary=:all: --require-hashes --no-cache-dir --retries 0`.

The authorised smoke run `42230812483` measured:

- `torch 2.15.0+cpu` and no CUDA identity;
- all 36 expected distributions and no forbidden `nvidia-*`, `cuda-*` or `triton` distribution;
- dependency/import consistency PASS;
- 1,249,054,720 allocated environment bytes;
- 449,081,344 bytes peak RSS.

That run did not download or load a model.

## Pinned models and proposed loading

### HHEM-2.1-Open

- Model: `vectara/hallucination_evaluation_model@de9a5e6ba9ba49531a022dba17e35ffeb2a6fad8`.
- Foundation config/tokenizer: `google/flan-t5-base@d76732216083fbc26a721b5cf3a653978fdb64ef`.
- Allowlisted bytes: 441,757,214.
- Route: build standard `T5ForTokenClassification` from the pinned FLAN config, load the exact HHEM safetensors with the documented `t5.` key-prefix handling, and use the pinned FLAN tokenizer. Remote code is not executed.

Vectara's current model card says Transformers 4.x and 5.x are supported. The route is statically consistent with the smoke-tested classes, but actual pinned-weight loading, CPU memory and runtime remain unmeasured.

### MiniCheck-Flan-T5-Large

- Model: `lytang/MiniCheck-Flan-T5-Large@96eafd01cee2d16cf81aaa2fb226b14f422a37b3`.
- Reference code: `Liyan06/MiniCheck@b58b9fa69acbd1015ec970fa65dd752413a053d2`.
- Allowlisted bytes: 3,136,026,916.
- Route: load the complete pinned local repository using `AutoTokenizer` and `AutoModelForSeq2SeqLM`, CPU only and `local_files_only=True`; calculate the documented first-decoder-token probability over IDs 3 and 209. Remote code and the broader MiniCheck package are not used.

The weight is a PyTorch `.bin`. The frozen `torch 2.15.0+cpu` exceeds the Transformers safety floor of torch 2.6 for `torch.load`; this removes that known version-floor blocker but is not proof that the 3.13-GB checkpoint will load inside the time and memory caps.

## Integrity route

Only allowlisted files may be downloaded. Large LFS objects have exact SHA-256 values. Small Git-backed files have exact byte sizes and Git blob SHA-1 values. Every file is checked before model loading. Loading then switches to local/offline mode.

No dependency version, model revision, evidence packet, answer, score rule or model behaviour was changed.
