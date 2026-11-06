# Stories Of Us — Dedicated Checker Comparison Package V02

Status: **PREPARED / EXECUTION LOCKED / CHECKER RELIABILITY UNTESTED**

This isolated package is the separately versioned technical repair of V01 and prepares the conditionally authorised bounded comparison of:

- `vectara/hallucination_evaluation_model` (HHEM-2.1-Open); and
- `lytang/MiniCheck-Flan-T5-Large`.

The comparison is deliberately narrower than the existing Stories Of Us verification contract. Each candidate receives one frozen atomic claim and the same complete frozen evidence packet, then returns a binary support score. A locally selected development threshold maps that score to `CANDIDATE_SUPPORTED` or `WITHHOLD`. The original three-way answer keys remain private scoring evidence; the models do not manufacture `UNSUPPORTED` versus `INSUFFICIENT_EVIDENCE`, explanations or citations.

The V01 package, public commit and zero-job workflow-validation failure remain unchanged. V02 moves runner-temporary path initialisation into a supported runtime step, repairs the launch command's YAML quoting, and uses a new workflow identity plus a new one-use lock. Before upload, live execution remains impossible without a separately created authority record whose generated V02 freeze-manifest hash matches this package.

Detailed validation and closeout are recorded in this package's versioned reports.

AUTONOMOUS AGENT: **HOLD**  
DEPLOYMENT: **NONE**
