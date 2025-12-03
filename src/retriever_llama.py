import os
import glob

from langfuse import observe
from llama_cloud_services import LlamaCloudIndex


class RetrieverLlama:
    def __init__(
        self,
        top_k=5,
        name: str = "bingo",
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
        self.api_key = os.getenv("LLAMA_API_KEY")
        self.name = name
        self.org_id = os.getenv("LLAMA_ORG")
        self.patterns = patterns or ["**/*.txt", "*.txt"]
        self.top_k = top_k
    
    async def _read_text_files(self, data_dir, index):
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
                        print(f"Uploading {p}...")
                        file_id = await index.aupload_file(p, wait_for_ingestion=True)
                        docs.append({"path": p, "file_id": file_id})
                        print(f"\tUploaded {p} as {file_id}") 
                except Exception:
                    continue
        
        return docs
    
    def index_exists(self):
        """Check if index and docs files exist."""
        index = LlamaCloudIndex(
            name=self.name,
            project_name="Default",
            organization_id=self.org_id,
            api_key=self.api_key,
        )
        return index is not None

    async def build_index(self, data_dir):
        index = await LlamaCloudIndex.acreate_index(
            name=self.name,
            project_name="Default",
            organization_id=self.org_id,
        )
        await self._read_text_files(data_dir, index)  
    
    @observe
    def query(self, query):
        index = LlamaCloudIndex(
            name=self.name,
            project_name="Default",
            organization_id=self.org_id,
            api_key=self.api_key,
        )

        chunk_retriever = index.as_retriever(
            dense_similarity_top_k=self.top_k,
            sparse_similarity_top_k=self.top_k,
            enable_reranking=True,
            rerank_top_n=3,
            chunk_size=500,
            chunk_overlap=50,
        )
        nodes = chunk_retriever.retrieve(query)
        context = "\n\n---\n\n".join(n.text for n in nodes)
        retrieved = [
            f"{n.metadata.get('file_name')} {len(n.text)} chars"
             for n in nodes
        ]
        return retrieved, context