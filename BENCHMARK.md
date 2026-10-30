# Stories Of Us experimental AI summary benchmark

This repository contains a manual, test-only CPU benchmark for two small open-weight language models. It does not contain the Stories Of Us website or operational Agent.

## Safety boundary

- Manual `workflow_dispatch` only.
- Read-only repository permission.
- Standard free public-repository runner.
- No secrets, scheduled jobs, branch writes, deployment or Netlify integration.
- Model weights are downloaded temporarily, checksum-verified and never committed or uploaded as artifacts.
- Results are labelled experimental, not editorially approved, and not for publication.

## Models

- IBM Granite 3.3 2B Instruct Q4_K_M.
- Qwen3 4B Q4_K_M.

Exact revisions, licences, sizes and checksums are in `benchmark/model_manifest.json`.

## Evaluation

Three public-source articles are represented by short, public-safe factual evidence packets. No complete article, protected curated data or private project documentation is included.

The current run tests verified evidence without protected curated examples. The protected example-assisted comparison requires separate disclosure approval and is not included.

## Running

Open the **Actions** tab, select **Manual AI summary benchmark**, choose **Run workflow**, and use the `main` branch. The workflow has no automatic trigger.

The output artifact is retained for seven days. A technical result is not human editorial approval and does not authorise publication or deployment.
