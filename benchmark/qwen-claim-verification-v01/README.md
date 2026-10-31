# Qwen claim verification benchmark V01

This public-safe, experimental benchmark compares the existing Qwen V04 baseline with a two-main-points authoring method. The second method uses a separate Qwen context to classify material claims and allows one controlled rewrite when the supplied evidence can support a correction.

The checker is a semantic experimental safeguard, not an independent editorial reviewer. It uses the same model as the writer and cannot establish production reliability by itself.

The package contains two historical diagnostic cases and four frozen final cases across Tech and Arts. It contains concise original fact paraphrases and publisher links, not complete articles, protected curated summaries or private project documents.

The workflow is manual-only, uses a pinned Qwen3 4B GGUF and pinned llama.cpp revision on a standard public-repository GitHub runner, and does not publish or deploy anything.
