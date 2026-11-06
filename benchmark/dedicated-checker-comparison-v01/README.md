# Stories Of Us — Dedicated Checker Comparison Package V01

Status: **PREPARED / EXECUTION LOCKED / CHECKER RELIABILITY UNTESTED**

This isolated package prepares a bounded comparison of:

- `vectara/hallucination_evaluation_model` (HHEM-2.1-Open); and
- `lytang/MiniCheck-Flan-T5-Large`.

The comparison is deliberately narrower than the existing Stories Of Us verification contract. Each candidate receives one frozen atomic claim and the same complete frozen evidence packet, then returns a binary support score. A locally selected development threshold maps that score to `CANDIDATE_SUPPORTED` or `WITHHOLD`. The original three-way answer keys remain private scoring evidence; the models do not manufacture `UNSUPPORTED` versus `INSUFFICIENT_EVIDENCE`, explanations or citations.

No installation, model download or inference has occurred. Live execution is impossible without a separately created, owner-approved authority record whose freeze-manifest hash matches this package. The package includes a local GitHub Actions workflow **draft**, not a repository workflow.

Detailed closeout is in `reports/07_governance_handover.md`.

AUTONOMOUS AGENT: **HOLD**  
DEPLOYMENT: **NONE**
