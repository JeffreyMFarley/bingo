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


class RetrieverFaiss:
    def __init__(
        self,
        model_name="all-MiniLM-L6-v2",
        index_path="index.faiss",
        docs_path="docs.json",
        top_k=5,
        patterns=None
    ):
        """
        Initialize RAG Index with configuration.
        
        Args:
            model_name: Name of the sentence transformer model
            index_path: Path to save/load the FAISS index
            docs_path: Path to save/load the documents JSON
            top_k: Number of top results to retrieve
            patterns: List of glob patterns for finding text files
        """
        self.model_name = model_name
        self.index_path = index_path
        self.docs_path = docs_path
        self.top_k = top_k
        self.patterns = patterns or ["**/*.txt", "*.txt"]
        
        self.model = None
        self.index = None
        self.docs = None
    
    def _ensure_model(self):
        """Lazy load the sentence transformer model."""
        if self.model is None:
            if SentenceTransformer is None:
                raise RuntimeError("sentence-transformers is required. Install from requirements.txt")
            self.model = SentenceTransformer(self.model_name)
        return self.model
    
    def read_text_files(self, data_dir):
        """Read all text files from data directory."""
        docs = []
        found = set()
        
        for pat in self.patterns:
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
    
    def build_index(self, data_dir):
        """Build FAISS index from documents."""
        if faiss is None:
            raise RuntimeError("faiss (faiss-cpu) is required. Install from requirements.txt")

        self.docs = self.read_text_files(data_dir)
        if not self.docs:
            print(f"No .txt files found in {data_dir}. Add plaintext docs and try again.")
            return

        model = self._ensure_model()
        texts = [d["text"] for d in self.docs]
        embeddings = model.encode(texts, show_progress_bar=True, convert_to_numpy=True)
        
        dim = embeddings.shape[1]
        self.index = faiss.IndexFlatL2(dim)
        self.index.add(np.asarray(embeddings, dtype="float32"))
        
        faiss.write_index(self.index, self.index_path)
        with open(self.docs_path, "w", encoding="utf-8") as f:
            json.dump(self.docs, f, ensure_ascii=False, indent=2)
        
        print(f"Saved index to {self.index_path} and docs to {self.docs_path}")
    
    def load_index(self):
        """Load FAISS index and documents from disk."""
        if faiss is None:
            raise RuntimeError("faiss (faiss-cpu) is required. Install from requirements.txt")
        
        self.index = faiss.read_index(self.index_path)
        with open(self.docs_path, "r", encoding="utf-8") as f:
            self.docs = json.load(f)
        
        return self.index, self.docs
    
    @observe
    def query(self, query, top_k=None):
        """
        Query the index and return top-k results.
        
        Args:
            query: Query string
            top_k: Number of results (uses self.top_k if not provided)
        
        Returns:
            Tuple of (retrieved_docs, context_string)
        """
        if self.index is None or self.docs is None:
            self.load_index()
        
        k = top_k or self.top_k
        model = self._ensure_model()
        
        q_emb = model.encode([query], convert_to_numpy=True)
        q_emb = np.asarray(q_emb, dtype="float32")
        D, I = self.index.search(q_emb, k)
        
        retrieved = [self.docs[i] for i in I[0] if i < len(self.docs)]
        context = "\n\n---\n\n".join(d.get("text", "") for d in retrieved)
        
        return retrieved, context