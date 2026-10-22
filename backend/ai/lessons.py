"""The lessons behind the RAG coach (Phase 7): loading, chunking and keyword search.

Pure code: no database, no network. The lessons are Markdown files in
``backend/lessons/``. Each ``## `` section becomes one **chunk**, the unit that is
embedded, searched and cited. A chunk's id is stable as long as its lesson file and
section heading don't change, e.g. ``02-notation#clockwise-primes-and-doubles``.

``KeywordIndex`` is BM25, the classic search-engine ranking. The coach uses it when
there are no embeddings (no key, the embedding request failed, the index is still
being built), so retrieval always works.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

LESSONS_DIR = Path(__file__).resolve().parent.parent / "lessons"


@dataclass(frozen=True)
class Chunk:
    id: str  # "02-notation#clockwise-primes-and-doubles"
    lesson: str  # "02-notation"
    lesson_title: str
    section: str  # the "## " heading
    text: str  # the section's body

    def content(self) -> str:
        """What is embedded and searched: titles too, so "notation" finds the notation lesson."""
        return f"{self.lesson_title}: {self.section}\n{self.text}"


@dataclass(frozen=True)
class Lesson:
    slug: str
    title: str
    summary: str
    chunks: Tuple[Chunk, ...]

    def to_dict(self) -> Dict[str, object]:
        return {
            "slug": self.slug,
            "title": self.title,
            "summary": self.summary,
            "sections": [{"id": c.id, "title": c.section, "text": c.text} for c in self.chunks],
        }


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_lesson(slug: str, markdown: str) -> Lesson:
    """``# Title``, a one-paragraph summary, then ``## Section`` blocks."""
    title, summary_lines, sections = slug, [], []
    current: List[str] = []
    heading = None
    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            if heading is not None:
                sections.append((heading, current))
            heading, current = line[3:].strip(), []
        elif heading is None:
            summary_lines.append(line)
        else:
            current.append(line)
    if heading is not None:
        sections.append((heading, current))
    chunks = tuple(
        Chunk(f"{slug}#{slugify(name)}", slug, title, name, "\n".join(lines).strip())
        for name, lines in sections
    )
    return Lesson(slug, title, " ".join(" ".join(summary_lines).split()), chunks)


def load_lessons(directory: Path = LESSONS_DIR) -> List[Lesson]:
    """Every ``*.md`` lesson, in file-name order (01-, 02-, ...)."""
    return [parse_lesson(path.stem, path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.md"))]


def all_chunks(lessons: Sequence[Lesson]) -> List[Chunk]:
    return [chunk for lesson in lessons for chunk in lesson.chunks]


# --------------------------------------------------------------------------------------
# Keyword search (BM25)
# --------------------------------------------------------------------------------------

STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i if in is it its me my of on or so that the "
    "then there this to was what when where which who why will with you your".split()
)


def tokens(text: str) -> List[str]:
    """Lower-case words without stopwords; a plural "s" is dropped ("stickers" -> "sticker")."""
    words = re.findall(r"[a-z0-9]+'?", text.lower())
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if w not in STOPWORDS]


class KeywordIndex:
    """BM25 over the chunks: rare words that appear often in a chunk score highest."""

    K1 = 1.5  # how quickly repeating a word stops adding to the score
    B = 0.75  # how much long chunks are penalised

    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self.chunks = list(chunks)
        self._terms = [Counter(tokens(chunk.content())) for chunk in self.chunks]
        self._lengths = [sum(terms.values()) for terms in self._terms]
        self._average = sum(self._lengths) / max(len(self._lengths), 1)
        document_frequency = Counter(word for terms in self._terms for word in terms)
        n = len(self.chunks)
        self._idf = {word: math.log(1 + (n - df + 0.5) / (df + 0.5)) for word, df in document_frequency.items()}

    def search(self, query: str, k: int = 4) -> List[Tuple[Chunk, float]]:
        words = tokens(query)
        scored = []
        for chunk, terms, length in zip(self.chunks, self._terms, self._lengths):
            score = 0.0
            for word in words:
                tf = terms.get(word, 0)
                if tf:
                    norm = tf + self.K1 * (1 - self.B + self.B * length / self._average)
                    score += self._idf[word] * tf * (self.K1 + 1) / norm
            if score > 0:
                scored.append((chunk, round(score, 4)))
        scored.sort(key=lambda item: -item[1])
        return scored[:k]


# --------------------------------------------------------------------------------------
# A small evaluation set: questions and the section that answers each one
# --------------------------------------------------------------------------------------

EVAL_QUESTIONS: List[Tuple[str, str]] = [
    ("What does R prime mean?", "02-notation#clockwise-primes-and-doubles"),
    ("Which way do I turn B?", "02-notation#the-tricky-sides-b-l-and-d"),
    ("How do I undo a sequence of moves?", "02-notation#reading-a-sequence"),
    ("Why does the centre decide the colour of a side?", "01-the-cube#the-centres-decide-the-colours"),
    ("Which colour is opposite white?", "01-the-cube#the-colour-scheme"),
    ("What is God's number?", "01-the-cube#how-many-positions-there-are"),
    ("Red and orange look the same to the camera, what can I do?", "03-scanning#good-light-no-glare"),
    ("Can I scan the sides in any order?", "03-scanning#any-order-works"),
    ("Why is my cube not solvable when it has 10 yellow stickers?", "04-why-unsolvable#nine-of-each-colour"),
    ("What is corner twist and parity?", "04-why-unsolvable#twist-flip-and-parity"),
    ("How do I make the yellow cross?", "05-beginner-method#step-4-the-yellow-cross"),
    ("How do I insert a middle layer edge?", "05-beginner-method#step-3-the-middle-layer"),
    ("How does the Kociemba solver find a solution?", "06-how-the-solver-works#kociemba-s-two-phase-algorithm"),
    ("How should I hold the cube while following the solution?", "07-following-a-solution#hold-the-cube-the-right-way"),
    ("What should I learn after the beginner method?", "08-practice#what-to-learn-next"),
]


def evaluate(search: Callable[[str], Sequence[str]], top: int = 3) -> Dict[str, object]:
    """Recall@top: in how many questions is the right section among the first ``top`` results?"""
    misses = []
    for question, expected in EVAL_QUESTIONS:
        if expected not in list(search(question))[:top]:
            misses.append(question)
    total = len(EVAL_QUESTIONS)
    return {"hits": total - len(misses), "total": total, "misses": misses}
