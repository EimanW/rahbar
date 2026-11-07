# ADR 0004: LLM provider behind an interface, Ollama on the laptop by default

## Status
Accepted · 2026-11-05

## Context
Section 3.5: the provider must be pluggable via `LLM_PROVIDER`, with at least one mode fully
supported and a swap being one file. minikube on a student laptop has 6 GB; an in-cluster
Ollama needs 8 GB and minutes of start-up. Hosted free tiers need a key and send questions and
retrieved passages to a third party.

## Decision
- **Interface** (`api/app/providers/llm/base.py`): `complete(messages, schema, temperature)
  -> Completion(text, tokens_in, tokens_out)`. Prompt building, validation, the single retry,
  the fallback and the citation check are NOT provider code; they live once in
  `services/generation.py` and `services/answer.py`, so a new provider cannot forget them.
- **Default: `ollama-host`** (`providers/llm/ollama.py`): Ollama on the laptop, reached at
  `http://host.minikube.internal:11434`, model `llama3.2:3b`, the Answer JSON schema in
  Ollama's `format` field (constrained decoding), `num_ctx` set explicitly. The same class
  serves `ollama-incluster` with a different `OLLAMA_URL`.
- **`hosted`** (`providers/llm/hosted.py`): any OpenAI-compatible endpoint (Groq, Google AI
  Studio, OpenRouter) with `response_format: json_object`. The key exists only as the
  Kubernetes Secret `rahbar-secret`, created on the command line (`make secret`); it is never in
  a committed file or a log line.
- **`stub`** (`providers/llm/stub.py`): deterministic, no network; used by every unit test,
  by the CI e2e-eval job and by the CD smoke test.
- **Embeddings are pinned separately** (`EMBED_MODEL`, one ConfigMap key read by both the
  indexer and the api, enforced by the readiness guardrail). In `ollama-host` mode we embed
  through the same laptop Ollama (`nomic-embed-text`, 768 dimensions).

## Data governance
- The corpus is public university documents, so retrieved passages carry no personal data.
- Questions may contain personal details. With `ollama-host` nothing leaves the laptop. With
  `hosted`, questions and passages go to the provider; the README says so. Free-tier terms
  differ on whether inputs may be retained or used, so `hosted` is not the default.
- Logs record chunk ids, scores and token counts, never the API key; the question text is not
  logged by the answer path.

## Options considered
- `ollama-incluster` as default: no dependency on the host, but 8 GB minikube and a
  `startupProbe` with `failureThreshold: 30` for weight loading; too heavy for our laptops.
- Hosted as default: fastest answers, but a key to manage and data leaving the machine.

## Consequences
- Easier: tests and CI never need a model; changing provider is a ConfigMap edit plus a
  rollout restart.
- Harder: the demo depends on the laptop running `OLLAMA_HOST=0.0.0.0 ollama serve`, and the
  api's NetworkPolicy must allow egress to port 11434 outside the cluster.
