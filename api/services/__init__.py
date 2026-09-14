"""Service layer — one module per block in the SysML structure diagram.

Class names are traceability anchors and MUST NOT be renamed or merged:
    EmbeddingService, VectorStore, LLMService,
    DeduplicationService, RAGPipeline, LibrarySyncService

Phase 1 ships these as typed interfaces whose methods raise NotImplementedError.
Agent B fills the bodies in Phase 2 without changing the signatures.
"""

from api.services.deduplication import DeduplicationService
from api.services.embedding import EmbeddingService
from api.services.library_sync import LibrarySyncService
from api.services.llm import LLMService
from api.services.rag_pipeline import RAGPipeline
from api.services.vector_store import VectorStore

__all__ = [
    "DeduplicationService",
    "EmbeddingService",
    "LLMService",
    "LibrarySyncService",
    "RAGPipeline",
    "VectorStore",
]
