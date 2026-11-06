# Preserved scoring and resource envelope

## Experiment

- Four known development summaries: 10 atomic claims (7 supported, 2 unsupported, 1 insufficient-evidence reference label).
- Twelve checker-new cached/constructed evaluation summaries: 29 atomic claims.
- Approved AAPD evidence correction preserved.
- Identical evidence and claims for both candidates.
- Original three-way answer keys retained for assessment; each binary candidate emits only a support score and the experimental decision `CANDIDATE_SUPPORTED` or `WITHHOLD`.

Development selects a threshold from 0.05–0.95. It must make zero supported decisions on the three non-supported claims and accept at least five of seven supported claims. Evaluation answers never enter model inputs or threshold selection.

Evaluation requires 29 valid primary scores, zero false approval of non-supported claims, at least 18/21 supported claims recognised, zero unsafe or insufficient summaries supported, at least 3/4 supported summaries supported, and repeatability with identical decisions and maximum score drift `0.00001`. Rejecting everything fails.

## Exact computation cap

| Work | Maximum computations |
|---|---:|
| Development | 20 (10 per candidate) |
| Conditional evaluation | 58 (29 per candidate) |
| Conditional repeatability | 12 (6 per candidate) |
| **Total** | **90** |

There are no probes, warm-ups, retries or extra chunks. Each logical evaluation is one model forward computation.

## Resource caps

- 45 minutes, beginning before dependency installation and including install, downloads, loads, token counting, inference, scoring and result creation.
- Peak task RSS: 12,000,000,000 bytes (12 GB decimal), monitored across the active candidate subprocess and descendants.
- Installed dependency environment: 3,221,225,472 bytes (3 GiB).
- Candidate model/tokenizer storage: 4,000,000,000 bytes.
- Other task temporary material: 1,000,000,000 bytes.
- Combined task-created material: 8,000,000,000 bytes.
- Result artifact: 5,000,000 bytes; no weights.
- Minimum free disk before installation: 10,737,418,240 bytes (10 GiB).
- Expenditure: £0; standard public runner only; no larger/paid fallback.

Known allowlisted file totals are 441,757,214 bytes for HHEM and 3,136,026,916 bytes for MiniCheck, each below the candidate cap. These are file totals, not measured installed/cache or peak-disk values. The future workflow records actual allocated and logical sizes before applying guards.

Storage accounting uses `lstat`, counts each inode once, does not follow snapshot symlinks, and reports symlink-target logical size only as a diagnostic. A synthetic regular-file/hard-link/symlink test confirms that one stored blob is not counted three times.
