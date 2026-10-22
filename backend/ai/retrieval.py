"""Retrieval for the RAG coach (Phase 7): find the lesson sections that answer a question.

    question ──► embed (Gemini) ──► nearest lesson sections ──► the coach quotes and cites them

Three ways to search, best first; the index uses the best one that works right now:

1. **pgvector** (Postgres, e.g. Neon): the database compares the question's embedding with
   every stored section embedding (``<=>`` = cosine distance) and returns the nearest.
2. **vectors in Python** (SQLite locally, or a Postgres without pgvector): the same
   comparison with NumPy.
3. **keywords** (BM25, no embeddings at all): no API key, the embedding request failed,
   or the index is still being built.

Embeddings are made once per lesson section and stored in ``lesson_embeddings``. At
start-up ``sync()`` embeds only sections that are new or changed (a sha256 of the text
says so) and deletes rows for sections that no longer exist, so a redeploy costs
nothing unless a lesson changed.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from sqlalchemy import delete, select, text

from backend.ai.lessons import Chunk, KeywordIndex, Lesson, all_chunks
from backend.ai.llm import Embedder, LLMError
from backend.db.database import Database, StorageError
from backend.db.models import LessonEmbeddingRow

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float  # cosine similarity (vectors) or BM25 score (keywords): higher is better

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.chunk.id,
            "lesson": self.chunk.lesson_title,
            "section": self.chunk.section,
            "text": self.chunk.text,
            "score": round(self.score, 4),
        }


@dataclass(frozen=True)
class SearchResult:
    hits: List[Hit]
    method: str  # "pgvector", "vectors in Python" or "keywords"
    note: Optional[str] = None  # why a better method wasn't used


def content_hash(chunk: Chunk) -> str:
    return hashlib.sha256(chunk.content().encode("utf-8")).hexdigest()


class LessonIndex:
    """The lessons, their stored embeddings, and search over them."""

    def __init__(self, lessons: Sequence[Lesson], database: Optional[Database] = None,
                 embedder: Optional[Embedder] = None) -> None:
        self.lessons = list(lessons)
        self.chunks = all_chunks(self.lessons)
        self._by_id = {chunk.id: chunk for chunk in self.chunks}
        self.keywords = KeywordIndex(self.chunks)
        self._db = database
        self._embedder = embedder
        self._lock = threading.Lock()
        self._vectors: Dict[str, np.ndarray] = {}  # chunk id -> unit vector (SQLite search)
        self._embedded = 0
        self._error: Optional[str] = None
        self.pgvector = False  # set by sync(): is the embedding column a real pgvector column?

    @property
    def ready(self) -> bool:
        """True when every section has an embedding from the current model."""
        return self._embedder is not None and self._embedded == len(self.chunks) > 0

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "lessons": len(self.lessons),
                "sections": len(self.chunks),
                "embedded": self._embedded,
                "model": self._embedder.model if self._embedder else None,
                "search": ("pgvector" if self.pgvector else "vectors in Python") if self.ready else "keywords",
                "error": self._error,
            }

    # ------------------------------------------------------------------
    def sync(self) -> None:
        """Make the stored embeddings match the lessons (embed only what changed)."""
        if self._db is None or self._embedder is None:
            return
        model = self._embedder.model
        wanted = {chunk.id: content_hash(chunk) for chunk in self.chunks}
        try:
            with self._db.transaction("load lesson embeddings") as session:
                rows = {row.id: (row.content_hash, row.model) for row in session.scalars(select(LessonEmbeddingRow))}
            stale = [cid for cid, (digest, row_model) in rows.items() if wanted.get(cid) != digest or row_model != model]
            missing = [chunk for chunk in self.chunks if chunk.id not in rows or chunk.id in stale]
            if stale:
                with self._db.transaction("delete old lesson embeddings") as session:
                    session.execute(delete(LessonEmbeddingRow).where(LessonEmbeddingRow.id.in_(stale)))
            if missing:
                vectors = self._embedder.embed([chunk.content() for chunk in missing], "RETRIEVAL_DOCUMENT")
                with self._db.transaction("save lesson embeddings") as session:
                    for chunk, vector in zip(missing, vectors):
                        session.add(LessonEmbeddingRow(id=chunk.id, content_hash=wanted[chunk.id], model=model,
                                                       embedding=vector))
            with self._db.transaction("load lesson embeddings") as session:
                loaded = {row.id: row.embedding for row in session.scalars(select(LessonEmbeddingRow))}
                pgvector = self._db.dialect == "postgresql" and session.execute(text(
                    "SELECT udt_name FROM information_schema.columns "
                    "WHERE table_name = 'lesson_embeddings' AND column_name = 'embedding'"
                )).scalar() == "vector"
        except (LLMError, StorageError) as exc:
            with self._lock:
                self._error = str(exc)
            log.warning("Lesson embeddings not ready, the coach searches by keywords: %s", exc)
            return
        with self._lock:
            self._vectors = {cid: np.asarray(vector, dtype=np.float32) for cid, vector in loaded.items() if cid in wanted}
            self._embedded = len(self._vectors)
            self._error = None
            self.pgvector = pgvector
        log.info("Lesson index: %d sections, %d newly embedded", len(self.chunks), len(missing))

    # ------------------------------------------------------------------
    def search(self, query: str, k: int = 4) -> SearchResult:
        """The ``k`` sections closest to the question, with the method that was used."""
        note = None
        if self.ready:
            try:
                (vector,) = self._embedder.embed([query], "RETRIEVAL_QUERY")  # type: ignore[union-attr]
                if self.pgvector:
                    return SearchResult(self._search_pgvector(vector, k), "pgvector")
                return SearchResult(self._search_numpy(vector, k), "vectors in Python")
            except (LLMError, StorageError) as exc:
                note = f"vector search failed ({exc}), so keywords were used"
        elif self._embedder is not None:
            note = self.status()["error"] or "the lesson index is still being built"
        hits = [Hit(chunk, score) for chunk, score in self.keywords.search(query, k)]
        return SearchResult(hits, "keywords", note)

    def _search_pgvector(self, vector: List[float], k: int) -> List[Hit]:
        literal = "[" + ",".join(repr(float(x)) for x in vector) + "]"
        sql = text(
            "SELECT id, 1 - (embedding <=> CAST(:query AS vector)) AS similarity "
            "FROM lesson_embeddings WHERE model = :model ORDER BY embedding <=> CAST(:query AS vector) LIMIT :k"
        )
        with self._db.transaction("search lesson embeddings") as session:  # type: ignore[union-attr]
            rows = session.execute(sql, {"query": literal, "model": self._embedder.model, "k": k}).all()  # type: ignore[union-attr]
        return [Hit(self._by_id[row.id], float(row.similarity)) for row in rows if row.id in self._by_id]

    def _search_numpy(self, vector: List[float], k: int) -> List[Hit]:
        with self._lock:
            ids = list(self._vectors)
            matrix = np.stack([self._vectors[cid] for cid in ids])
        similarity = matrix @ np.asarray(vector, dtype=np.float32)  # unit vectors: dot product = cosine
        best = np.argsort(-similarity)[:k]
        return [Hit(self._by_id[ids[i]], float(similarity[i])) for i in best]

    def get(self, chunk_id: str) -> Optional[Chunk]:
        return self._by_id.get(chunk_id)
