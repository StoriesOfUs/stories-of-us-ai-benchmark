# Option C Automatic Claim Coverage V01

This isolated experiment evaluates whether Qwen3 4B can identify every material factual claim in its own complete summary, classify each claim's factual and temporal status, and pass each atomic claim to the existing self-contained evidence preparer and fixed DeBERTa verifier.

The evaluation contains three retained diagnostic summaries and five frozen new Qwen-authoring cases. The case membership, evidence and configuration were frozen before model execution. A separate fresh-context reviewer will create the reference claim inventories without seeing the automatic extractor or verifier results.

This is experimental evidence only. It is not an operational Agent, a publication approval gate or permission to publish. Qwen extraction uses the same underlying model as Qwen authoring and is not independent factual verification. DeBERTa retains the previously tested 0.5 entailment threshold and 0.3 margin.

Public-repository safeguards prohibit protected curated records, full publisher articles, private governance documents, credentials, production publication history and model weights. Inputs contain only limited original public-safe factual paraphrases and source links.
