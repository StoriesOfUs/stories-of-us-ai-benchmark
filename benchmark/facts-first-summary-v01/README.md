# Stories Of Us — Facts-First Summary Writing V01

This isolated public benchmark compares Qwen3 4B summary writing from a complete verified evidence packet with summary writing after Qwen automatically selects two supported facts. It then applies deterministic safeguards and the pinned independent DeBERTa NLI model.

The package is experimental. Outputs are labelled `EXPERIMENTAL AI OUTPUT — NOT EDITORIALLY APPROVED — NOT FOR PUBLICATION` and must not be published or treated as operational approval.

The benchmark:

- uses three newly frozen public-safe cases across Tech and Arts;
- keeps human reference facts separate from automatic fact-selection prompts;
- validates evidence identifiers and exact packet-span provenance;
- preserves factual status, attribution and time context;
- compares baseline and facts-first Qwen drafts;
- checks each two-sentence summary against verified evidence without reviving general-purpose claim extraction;
- permits at most one controlled facts-first rewrite; and
- runs six deliberately unsafe negative probes.

The workflow is manual-only and has read-only repository permissions. It does not publish, deploy, schedule itself, write to the repository or use protected curated Stories Of Us data.
