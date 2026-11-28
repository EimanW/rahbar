import chromadb

client = chromadb.HttpClient(host="chroma", port=8000)
source = client.get_collection("rahbar-a3")
name = "rahbar-a3-candidate"

target = client.get_or_create_collection(
    name,
    metadata=source.metadata
)

for offset in range(0, source.count(), 100):
    data = source.get(
        offset=offset,
        limit=100,
        include=["documents", "embeddings", "metadatas"]
    )
    target.upsert(
        ids=data["ids"],
        documents=data["documents"],
        embeddings=data["embeddings"].tolist(),
        metadatas=data["metadatas"]
    )

assert source.count() == target.count()
print("BASELINE COLLECTION:", source.name, source.count())
print("CANDIDATE COLLECTION:", target.name, target.count())
print("COLLECTION COPY: PASS")
