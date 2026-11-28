# RAHBAR Assignment 03 - Kubernetes Deployment

## Prerequisites

- Docker
- Kubernetes with kubectl
- Minikube or an equivalent local cluster
- Python and the project dependencies
- University documents downloaded into corpus/raw

The tested environment used Minikube with 2 CPUs and 4000 MB RAM.

## 1. Prepare the corpus and images

From the repository root, fetch the original corpus using the
existing project fetch workflow.

Generate the verification test corpus:

```bash
python eval/create_batch_b.py
```

Build the images:

```bash
docker build -t rahbar-api:dev api
docker build -f indexer/Dockerfile -t rahbar-indexer:a3 .
docker tag rahbar-indexer:a3 rahbar-indexer:dev
docker build -t rahbar-ui:dev ui
```

Load the images into Minikube:

```bash
minikube image load rahbar-api:dev
minikube image load rahbar-indexer:a3
minikube image load rahbar-indexer:dev
minikube image load rahbar-ui:dev
```

## 2. Deploy the base infrastructure

```bash
kubectl apply -k k8s/base
kubectl apply -f k8s/data-lake-pvc.yaml
kubectl -n rahbar patch cronjob reindex --type strategic --patch-file k8s/data-lake-patch.yaml
kubectl -n rahbar set image cronjob/reindex indexer=rahbar-indexer:a3
```

Chroma, Redis, API and UI run as Kubernetes workloads.
The ingestion Job and CronJob are responsible for writing to Chroma.
The API performs retrieval and generation.

The data lake PVC preserves quarantine files, archived documents,
verification reports and evaluation results.

## 3. Ingestion

Set CORPUS_DIR to /corpus and CHROMA_COLLECTION to rahbar-a3
in the rahbar-config ConfigMap.

```bash
kubectl -n rahbar edit configmap rahbar-config
kubectl -n rahbar create job a3-batch-a --from=cronjob/reindex
kubectl -n rahbar logs -f job/a3-batch-a
```

Repeat with a different Job name to verify unchanged documents.

Change CORPUS_DIR to /batch_b and create the Batch B Job:

```bash
kubectl -n rahbar create job a3-batch-b --from=cronjob/reindex
kubectl -n rahbar logs -f job/a3-batch-b
```

Restart the API after changing its configuration.

## 4. Candidate deployment

The baseline collection is rahbar-a3.
The candidate collection is rahbar-a3-candidate.

```bash
kubectl apply -f k8s/clone-code-configmap.yaml
kubectl apply -f k8s/clone-collection-job.yaml
kubectl -n rahbar wait --for=condition=complete job/a3-clone-collection --timeout=180s
kubectl apply -f k8s/candidate-networkpolicy.yaml
kubectl apply -f k8s/api-candidate.json
kubectl apply -f k8s/api-candidate-service.json
kubectl -n rahbar rollout status deployment/api-candidate
```

The tested candidate uses a relevance floor of 0.30 and disables
semantic cache hits using a cache threshold of 1.01.

## 5. Evaluation and regression gate

```bash
kubectl apply -f k8s/eval-code-configmap.yaml
kubectl apply -f k8s/eval-gate-configmap.yaml
kubectl apply -f k8s/eval-networkpolicy.yaml
kubectl apply -f k8s/eval-job.yaml
kubectl -n rahbar logs -f job/a3-eval
```

The evaluation Job exits with a nonzero status when the gate fails.
Thresholds are stored in a ConfigMap and can be changed without
rebuilding the image.

Delete the completed Job before rerunning it.

Evaluation evidence is stored in eval/results and on the data lake PVC.

## 6. Controlled rollout and rollback

Promote only after the candidate passes its evaluation gate.

```bash
kubectl -n rahbar set env deployment/api CHROMA_COLLECTION=rahbar-a3-candidate RELEVANCE_FLOOR=0.30 CACHE_THRESHOLD=1.01
kubectl -n rahbar rollout status deployment/api
kubectl -n rahbar rollout history deployment/api
```

The API uses a rolling update with maxUnavailable set to zero.

Rollback:

```bash
kubectl -n rahbar rollout undo deployment/api
kubectl -n rahbar rollout status deployment/api
```

## 7. Observability

```bash
kubectl -n rahbar port-forward svc/api 18080:8000
```

Endpoints:

- http://localhost:18080/healthz
- http://localhost:18080/readyz
- http://localhost:18080/metrics
- http://localhost:18080/api/ask

Query traces are emitted as JSONL to stdout and the traces PVC.

Replay a recorded query:

```bash
python eval/trace_tools.py replay --id fda167ed3b714fa2a07502f780c9af20
python eval/trace_tools.py metrics --hours 24
```

## 8. Incremental lifecycle tests

```bash
kubectl apply -f k8s/lifecycle-code-configmap.yaml
kubectl apply -f k8s/lifecycle-job.yaml
kubectl -n rahbar logs -f job/a3-small-lifecycle
```

The isolated test collection verifies initial indexing, unchanged
documents, changed documents, deletion, restoration, superseded
version exclusion and metadata-based version rollback.

## 9. Resource configuration

API:
- CPU request: 100m
- CPU limit: 500m
- Memory request: 192Mi
- Memory limit: 512Mi

Indexer:
- CPU request: 250m
- CPU limit: 1
- Memory request: 512Mi
- Memory limit: 1536Mi

Observed API resident memory was approximately 95.4 MiB.
The memory request provides headroom above this observation.

Metrics Server was unavailable in the tested cluster.
Process-level memory and Prometheus metrics were used instead.
CPU sizing was not independently validated under sustained load.

## 10. Evidence and limitations

Actual experiment results are committed under eval/results and traces.

The evaluation uses a deterministic hash embedding model and a stub
generation provider. Extractive faithfulness measures textual support,
not semantic answer correctness.

The version rollback test verifies metadata-based restoration rather
than independently restoring an archived raw document.

The unified evaluation runner requires a reachable API and collected
query traces. Its individual evaluation components were tested.

These setup instructions describe the tested components, but a complete
fresh-cluster installation was not independently rerun.
