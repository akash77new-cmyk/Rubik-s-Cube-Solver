"""The AI evaluation suite (tools/eval_ai.py): its offline evaluations pass their gates."""

from backend.ai.agent import FINAL_ANSWER
from backend.ai.fake import ScriptedLLM, tool_call
from backend.ai.llm import LLMRequest
from tools import eval_ai


def test_retrieval_guardrails_and_fallbacks_pass_their_gates():
    retrieval = eval_ai.eval_retrieval()
    assert retrieval["gate"] and retrieval["keywords"]["recall@3"] >= 13
    guardrails = eval_ai.eval_guardrails()
    assert guardrails["passed"] == guardrails["total"] == 14, guardrails["cases"]
    assert eval_ai.eval_fallbacks()["gate"]


def test_repair_and_beginner_evaluations_on_a_few_cases():
    repair = eval_ai.eval_repair(per_kind=3)
    assert repair["gate"] and repair["kinds"]["two, ambiguous"]["uniqueFix"] == 0
    assert eval_ai.eval_beginner(count=5)["gate"]


def test_a_misread_case_keeps_the_true_colours():
    scan, readings, truth = eval_ai.misread_case(1, "doubt", 2)
    assert not scan.validate().ok and len(truth) == 2
    for face, index, true_color in truth:
        assert readings[face][index]["confidence"] == 0.51
        assert readings[face][index]["alternatives"][1]["color"] == true_color


def test_the_offline_report_renders(tmp_path):
    results = {
        "retrieval": eval_ai.eval_retrieval(),
        "repair": eval_ai.eval_repair(per_kind=2),
        "beginner": eval_ai.eval_beginner(count=2),
        "guardrails": eval_ai.eval_guardrails(),
        "fallbacks": eval_ai.eval_fallbacks(),
    }
    results["allGates"] = True
    text = eval_ai.offline_markdown(results, {"date": "today", "commit": "abc1234"})
    assert text.startswith("# AI evaluation: offline") and "| Keywords (BM25) |" in text


def test_the_live_pacing_counts_answers_and_its_own_waits(monkeypatch):
    slept = []
    monkeypatch.setattr(eval_ai.time, "sleep", slept.append)
    model = ScriptedLLM([tool_call("search_lessons", query="cross"), tool_call(FINAL_ANSWER, message="Hi", citations=[])])
    paced = eval_ai.Paced(model, per_minute=60)
    for _ in range(2):
        paced.generate(LLMRequest(system="s", messages=[]))
    assert paced.final_answers == 1  # a lesson search, then one answer: accepted first try
    assert len(slept) == 1 and paced.waited == sum(slept) > 0.9  # the 2nd request waited about 1 s
