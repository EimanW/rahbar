#!/usr/bin/env bash
# Measure recall@5 for several (CHUNK_SIZE, CHUNK_OVERLAP) settings on the live cluster
# (section 3.1: "tune chunking with measurements, not guesses").
#   scripts/sweep_chunking.sh            # uses the Ingress (INGRESS_IP, default minikube ip)
# For each setting: patch the ConfigMap, re-index with a Job from the CronJob template,
# wait, flush the cache namespace by virtue of the new index_version, run the eval.
# Prints a Markdown table to paste into docs/PIPELINE.md. Restores the shipped values.
set -euo pipefail
NS=${NS:-rahbar}
INGRESS_IP=${INGRESS_IP:-$(minikube ip)}
HOST=${HOST:-rahbar.local}
CONFIGS=${CONFIGS:-"200:30 300:50 500:80"}
SHIPPED_SIZE=$(kubectl -n "$NS" get configmap rahbar-config -o jsonpath='{.data.CHUNK_SIZE}')
SHIPPED_OVERLAP=$(kubectl -n "$NS" get configmap rahbar-config -o jsonpath='{.data.CHUNK_OVERLAP}')

echo "| Size (words) | Overlap (words) | recall@3 | recall@5 | exact recall@5 | Chunks stored | Amplification |"
echo "| --- | --- | --- | --- | --- | --- | --- |"
for cfg in $CONFIGS; do
  size=${cfg%%:*}; overlap=${cfg##*:}
  kubectl -n "$NS" patch configmap rahbar-config --type merge \
    -p "{\"data\":{\"CHUNK_SIZE\":\"$size\",\"CHUNK_OVERLAP\":\"$overlap\"}}" >/dev/null
  job="sweep-$size-$overlap-$(date +%s)"
  kubectl -n "$NS" create job --from=cronjob/reindex "$job" >/dev/null
  kubectl -n "$NS" wait --for=condition=complete "job/$job" --timeout=1800s >/dev/null
  summary=$(kubectl -n "$NS" logs "job/$job" | grep '"chunking summary"' | tail -1)
  chunks=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['chunks'])" "$summary")
  amp=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['amplification'])" "$summary")
  sleep 20   # the api caches collection metadata for 15 s
  python3 eval/run_eval.py --api "http://$INGRESS_IP" --host "$HOST" \
    --out "/tmp/sweep-$size-$overlap.json" --baseline /tmp/rahbar-no-baseline.json >/dev/null || true
  python3 - "$size" "$overlap" "$chunks" "$amp" "/tmp/sweep-$size-$overlap.json" <<'PY'
import json, sys
size, overlap, chunks, amp, path = sys.argv[1:]
r = json.load(open(path))
ex = r["recall@5_by_type"].get("exact")
print(f"| {size} | {overlap} | {r['recall@3']} | {r['recall@5']} | {ex} | {chunks} | {amp} |")
PY
done
kubectl -n "$NS" patch configmap rahbar-config --type merge \
  -p "{\"data\":{\"CHUNK_SIZE\":\"$SHIPPED_SIZE\",\"CHUNK_OVERLAP\":\"$SHIPPED_OVERLAP\"}}" >/dev/null
echo
echo "restored CHUNK_SIZE=$SHIPPED_SIZE CHUNK_OVERLAP=$SHIPPED_OVERLAP; re-index with: make index"
