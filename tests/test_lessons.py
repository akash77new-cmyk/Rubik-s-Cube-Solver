"""The lessons: they load, every section is a chunk with a stable id, and keyword search finds them."""

from backend.ai.lessons import EVAL_QUESTIONS, KeywordIndex, all_chunks, evaluate, load_lessons, parse_lesson, tokens


def test_the_lessons_load_as_sections():
    lessons = load_lessons()
    assert len(lessons) == 8 and lessons[0].slug == "01-the-cube"
    chunks = all_chunks(lessons)
    assert len({chunk.id for chunk in chunks}) == len(chunks)  # ids are unique
    assert all(lesson.summary and len(lesson.chunks) >= 4 for lesson in lessons)
    assert all(chunk.text for chunk in chunks)
    assert {expected for _, expected in EVAL_QUESTIONS} <= {chunk.id for chunk in chunks}


def test_parsing_one_lesson():
    lesson = parse_lesson("09-x", "# Title\n\nA summary\non two lines.\n\n## First part\nText one.\n\n## Second: part\nText two.\n")
    assert (lesson.title, lesson.summary) == ("Title", "A summary on two lines.")
    assert [(c.id, c.section, c.text) for c in lesson.chunks] == [
        ("09-x#first-part", "First part", "Text one."),
        ("09-x#second-part", "Second: part", "Text two."),
    ]


def test_tokens_drop_stopwords_and_plurals():
    assert tokens("What are the stickers of R'?") == ["sticker", "r'"]


def test_keyword_search_answers_most_questions():
    index = KeywordIndex(all_chunks(load_lessons()))
    result = evaluate(lambda question: [chunk.id for chunk, _ in index.search(question, 3)])
    assert result["hits"] >= 13, result["misses"]  # 14 of 15 when this was written
