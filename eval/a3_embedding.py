import sys
import os
import httpx
import json
import time
import math
import statistics
import datetime
import random
from pathlib import Path

random.seed(42)
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "api"))

from app.hashembed import hash_embed

pairs = [
    ("What is the minimum CGPA?", "What minimum CGPA is required?"),
    ("How can I freeze a semester?", "How do I apply for semester freezing?"),
    ("What is the attendance requirement?", "How much attendance is required?"),
    ("How do I withdraw a course?", "What is the course withdrawal procedure?"),
    ("What is the tuition fee?", "How much tuition fee must I pay?"),
    ("Can I repeat a failed course?", "Am I allowed to repeat failed courses?"),
    ("What is academic probation?", "What does academic probation mean?"),
    ("How long is a bachelor degree?", "What is the duration of a bachelor degree?"),
    ("What are the graduation requirements?", "What requirements must I meet to graduate?"),
    ("How are grade points calculated?", "What is the grade point calculation method?"),
    ("What is the exam cheating penalty?", "What is the punishment for cheating in exams?"),
    ("Can students use AI tools?", "Are AI tools allowed for students?"),
    ("How do I register for courses?", "What is the course registration process?"),
    ("What is the scholarship eligibility?", "Who is eligible for a scholarship?"),
    ("When are final exams held?", "What is the schedule for final examinations?")
]

unrelated = [
    "The ocean contains salt water",
    "Elephants live in forests",
    "A telescope observes distant galaxies",
    "Chocolate melts when heated",
    "Penguins inhabit cold regions",
    "Cars require fuel to operate",
    "Rain falls from clouds",
    "The moon orbits Earth",
    "Birds build nests in trees",
    "Bread is made using flour",
    "Volcanoes release molten rock",
    "Guitars have strings",
    "Fish breathe through gills",
    "Mountains contain different minerals",
    "Bees produce honey"
]

MODEL = os.environ.get("EMBED_MODEL", "hash-bow-768")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

def embed(text):
    if MODEL == "nomic-embed-text":
        response = httpx.post(
            OLLAMA_URL + "/api/embed",
            json={
                "model": MODEL,
                "input": "search_query: " + text
            },
            timeout=120
        )
        response.raise_for_status()
        return response.json()["embeddings"][0]
    return hash_embed(text, 768)

def cosine(a, b):
    return sum(x*y for x,y in zip(a,b)) / (
        math.sqrt(sum(x*x for x in a)) *
        math.sqrt(sum(y*y for y in b))
    )

def evaluate():
    positive = []
    negative = []
    timings = []
    differences = []

    for i, (a,b) in enumerate(pairs):
        start = time.perf_counter()
        va = embed(a)
        timings.append((time.perf_counter()-start)*1000)

        vb = embed(b)
        vc = embed(unrelated[i])

        positive.append({
            "pair": [a,b],
            "cosine": cosine(va,vb)
        })

        negative.append({
            "pair": [a,unrelated[i]],
            "cosine": cosine(va,vc)
        })

        repeated = embed(a)
        differences.append(max(
            abs(x-y) for x,y in zip(va,repeated)
        ))

    pos = statistics.mean(p["cosine"] for p in positive)
    neg = statistics.mean(p["cosine"] for p in negative)

    return {
        "model": MODEL,
        "paraphrase_pairs": len(positive),
        "unrelated_pairs": len(negative),
        "mean_paraphrase_similarity": pos,
        "mean_unrelated_similarity": neg,
        "separation_gap": pos-neg,
        "mean_embedding_ms_per_text": statistics.mean(timings),
        "max_determinism_difference": max(differences),
        "positive_details": positive,
        "negative_details": negative
    }

first = evaluate()
second = evaluate()

keys = [
    "mean_paraphrase_similarity",
    "mean_unrelated_similarity",
    "separation_gap",
    "mean_embedding_ms_per_text",
    "max_determinism_difference"
]

result = {
    "seed": 42,
    "first": first,
    "second": second,
    "repeat_delta": {
        k: second[k]-first[k] for k in keys
    }
}

out = HERE / "results"
out.mkdir(exist_ok=True)
stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
path = out / f"embedding-{stamp}.json"
path.write_text(json.dumps(result,indent=2),encoding="utf-8")

print("EMBEDDING EVALUATION")
print("Model:", first["model"])
print("Paraphrase pairs:", first["paraphrase_pairs"])
print("Unrelated pairs:", first["unrelated_pairs"])

for k in keys:
    print(k, ":", first[k])

print("\nREPEATABILITY DIFFERENCE")
print(json.dumps(result["repeat_delta"],indent=2))
print("\nRESULT SAVED:",path)

