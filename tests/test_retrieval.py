"""Lesson embeddings in the database, and search with pgvector, NumPy or keywords.

Runs on SQLite, and on PostgreSQL (pgvector) too when CUBE_TEST_POSTGRES_URL is set.
"""

from sqlalchemy import select

from backend.ai.fake import HashEmbedder
from backend.ai.lessons import evaluate, load_lessons, parse_lesson
from backend.ai.llm import LLMUnavailable
from backend.ai.retrieval import LessonIndex
from backend.db.models import LessonEmbeddingRow


class BrokenEmbedder(HashEmbedder):
    def embed(self, texts, task):
        raise LLMUnavailable("Could not reach Gemini: offline")


def test_sync_embeds_once_and_search_uses_the_database(open_db):
    database = open_db()
    embedder = HashEmbedder()
    index = LessonIndex(load_lessons(), database, embedder)
    assert index.search("Which way do I turn B?").method == "keywords"  # not synced yet
    index.sync()
    assert embedder.documents == [35] and index.status()["embedded"] == 35
    expected = "pgvector" if database.dialect == "postgresql" else "vectors in Python"
    result = index.search("Which way do I turn B?")
    assert result.method == expected and result.hits[0].chunk.id == "02-notation#the-tricky-sides-b-l-and-d"
    assert evaluate(lambda q: [hit.chunk.id for hit in index.search(q, 3).hits])["hits"] >= 13

    LessonIndex(load_lessons(), database, embedder).sync()  # "a restart": nothing changed
    assert embedder.documents == [35]  # nothing new to embed


def test_only_changed_sections_are_embedded_again(open_db):
    database = open_db()
    embedder = HashEmbedder()
    LessonIndex(load_lessons(), database, embedder).sync()
    lessons = load_lessons()
    lessons[0] = parse_lesson("01-the-cube", "# The cube\n\nShort.\n\n## Three kinds of pieces\nChanged text.\n")
    LessonIndex(lessons, database, embedder).sync()
    assert embedder.documents == [35, 1]  # one changed section; the 3 removed ones are deleted
    with database.transaction("count") as session:
        assert len(session.scalars(select(LessonEmbeddingRow.id)).all()) == 32


def test_without_working_embeddings_search_falls_back_to_keywords(open_db):
    no_embedder = LessonIndex(load_lessons(), open_db(), None)
    no_embedder.sync()
    assert no_embedder.search("God's number").method == "keywords"
    assert no_embedder.status()["search"] == "keywords"

    broken = LessonIndex(load_lessons(), open_db(), BrokenEmbedder())
    broken.sync()
    result = broken.search("God's number")
    assert result.method == "keywords" and "offline" in result.note
    assert result.hits[0].chunk.id == "01-the-cube#how-many-positions-there-are"
