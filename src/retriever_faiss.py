import os
import glob
import json

import numpy as np
from langfuse import observe

try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None

try:
    import faiss
except Exception:
    faiss = None

def read_text_files(data_dir):
    docs = []
    patterns = ["**/*.txt", "*.txt"]

    found = set()
    for pat in patterns:
        for p in glob.glob(os.path.join(data_dir, pat), recursive=True):
            if p in found:
                continue
            found.add(p)
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    docs.append({"path": p, "text": fh.read()})
            except Exception:
                continue
    return docs


def build_index(docs, model_name, index_path="index.faiss", docs_path="docs.json"):
    if SentenceTransformer is None:
        raise RuntimeError("sentence-transformers is required. Install from requirements.txt")
    if faiss is None:
        raise RuntimeError("faiss (faiss-cpu) is required. Install from requirements.txt")
    model = SentenceTransformer(model_name)
    texts = [d["text"] for d in docs]
    embeddings = model.encode(texts, show_progress_bar=True, convert_to_numpy=True)
    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(np.asarray(embeddings, dtype="float32"))
    faiss.write_index(index, index_path)
    with open(docs_path, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)
    print(f"Saved index to {index_path} and docs to {docs_path}")


def load_index(index_path="index.faiss", docs_path="docs.json"):
    if faiss is None:
        raise RuntimeError("faiss (faiss-cpu) is required. Install from requirements.txt")
    index = faiss.read_index(index_path)
    with open(docs_path, "r", encoding="utf-8") as f:
        docs = json.load(f)
    return index, docs

@observe
def query_index(query, index, docs, embed_model_name, top_k):
    if SentenceTransformer is None:
        raise RuntimeError("sentence-transformers is required. Install from requirements.txt")

    emb_model = SentenceTransformer(embed_model_name)
    q_emb = emb_model.encode([query], convert_to_numpy=True)
    q_emb = np.asarray(q_emb, dtype="float32")
    D, I = index.search(q_emb, top_k)
    
    retrieved = [docs[i] for i in I[0] if i < len(docs)]
    context = "\n\n---\n\n".join(d.get("text", "") for d in retrieved)
    return retrieved, context