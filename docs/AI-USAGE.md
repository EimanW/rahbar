# AI usage

We used AI heavily and disclose it specifically, as the course policy asks.

| Tool | What it wrote or shaped | What we changed afterwards, and why |
| --- | --- | --- |
| Claude (Anthropic), in a Claude chat session with a code sandbox | First drafts of almost all of the non-starter code: the five indexer stages, `ChromaRetriever`, the Ollama/hosted/stub providers, `services/generation.py`, `cache.py`, `citations.py`, `answer.py`, `/readyz` and the embedding-pin guardrail, the four eval functions, the tests, the three Dockerfiles, every manifest under `k8s/`, both workflows, the docs and ADR drafts, and `eval/golden.yaml` (written from handbook facts it read through a web fetch) | TODO(team): list what you changed. Be specific: the values you measured and replaced (`kubectl top` sizes, the real-corpus chunk sweep, the relevance floor and cache threshold), golden-set sections you corrected against the PDFs, anything you rewrote so you can explain it in the viva |
| Claude, same session | Ran the local experiments behind FAILURE-ANALYSIS stages A, B, C and E and the fixture baseline, on a real Chroma 1.0.12 server with the CI embedder and the stub provider | The experiments found three bugs that were fixed: a table crop that cut text above tables, "earlier" in an injection question unlocking superseded documents, and a 500 instead of 503 on a broken embedding pin. They also led to the stale-citation gate |

What AI did **not** do: run anything on our cluster or GitHub. Every cluster number, screenshot
and evidence file in `docs/evidence/`, the CD run, the Docker Hub images and the real-corpus
`eval/results.json` / `eval/baseline.json` come from our own runs.
