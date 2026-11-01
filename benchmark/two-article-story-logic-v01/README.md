# Two-Article Facts and Story-Logic Diagnostic V01

This public-safe, manual-only benchmark compares three Qwen summary conditions for two named diagnostic articles. It uses the same independently prepared facts in Conditions A and B; only B receives an explicit verified relationship. Condition C uses Qwen's automatic two-fact and relationship packet without human correction.

The benchmark reuses the pinned Qwen3 4B CPU runtime and pinned DeBERTa NLI verifier from the earlier isolated facts-first experiment. DeBERTa uses unchanged conservative thresholds. No threshold is a publication approval rule.

All outputs are labelled **EXPERIMENTAL AI OUTPUT — NOT EDITORIALLY APPROVED — NOT FOR PUBLICATION**. The workflow is manual only, writes no repository content at runtime, uses no secrets and performs no deployment.
