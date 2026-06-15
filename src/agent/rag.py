import numpy as np
from typing import List, Dict, Any

class SimpleRAG:
    def __init__(self):
        self.documents = []
        self.embeddings = []

    def add_documents(self, docs: List[Dict[str, Any]]):
        """
        In production, this would use BGE-M3 and pgvector.
        Here we use a simple keyword-based mock for demonstration.
        """
        self.documents.extend(docs)

    def search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        # Mock similarity search
        query_terms = set(query.lower().split())
        scored_docs = []
        for doc in self.documents:
            content = doc['content'].lower()
            score = sum(1 for term in query_terms if term in content)
            scored_docs.append((score, doc))

        scored_docs.sort(key=lambda x: x[0], reverse=True)
        return [doc for score, doc in scored_docs[:k]]

    def get_context(self, query: str) -> str:
        results = self.search(query)
        context = "\n\n".join([f"Source: {d['source']}\n{d['content']}" for d in results])
        return context
