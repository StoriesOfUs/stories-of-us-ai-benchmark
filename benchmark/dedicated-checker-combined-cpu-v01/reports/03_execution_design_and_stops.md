# Execution design and stopping behaviour

## Global stages

1. Verify a future freeze-specific owner approval, the manifest, manual event, run number 1, attempt 1, one-use lock, public standard-runner and £0 conditions.
2. Install the proven exact CPU wheel lock. Record the environment size before applying the 3-GiB guard, run dependency checks and reject unexpected GPU distributions.

Any authority, freeze, dependency, total-budget, global time, peak-memory, combined-storage, contract or evidence-preservation failure stops the whole job.

## Per-candidate stages

Candidates run in fixed order: HHEM, then MiniCheck. Each is started in a separate monitored subprocess so process exit releases model memory before the next candidate.

1. Download only the candidate's allowlisted files at exact revisions.
2. Verify every byte size and content hash. Record inode-aware storage before the guard.
3. Load tokenizer and model on CPU from local files only.
4. Count every one of the 39 complete formatted claim inputs with the pinned tokenizer. Any input above 1,024 tokens stops that candidate; nothing is truncated or split.
5. Run ten development computations. Select the threshold using development answers only.
6. If and only if the development gate passes, run 29 evaluation and six repeatability computations.
7. Preserve the result, terminate the subprocess and delete that candidate's model directory.

A candidate-specific access, integrity, load, token, cache or development-gate failure is preserved and stops that candidate. The other candidate may continue only while every global control remains satisfied. This prevents one unavailable model from erasing evidence about the other without weakening global safety.

## One-use control

The prepared package has no approved authority file. A future run requires a new authority file bound to the exact freeze hash. The lock is consumed before dependency installation. The manual workflow accepts only run number 1 and attempt 1; retries are zero. Live candidate mode also refuses direct invocation without the consumed lock and an internal parent marker.
