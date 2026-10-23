"""The AI evaluation suite (tools/eval_ai.py): its offline evaluations pass their gates."""

from tools import eval_ai


def test_retrieval_guardrails_and_fallbacks_pass_their_gates():
    retrieval = eval_ai.eval_retrieval()
    assert retrieval["gate"] and retrieval["keywords"]["recall@3"] >= 13
    guardrails = eval_ai.eval_guardrails()
    assert guardrails["passed"] == guardrails["total"] == 12, guardrails["cases"]
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
