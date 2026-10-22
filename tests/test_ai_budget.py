"""The request budget: per minute and per 24 hours, refilled after a restart."""

import pytest

from backend.ai.budget import BudgetedLLM, RequestBudget
from backend.ai.fake import ScriptedLLM, text_reply
from backend.ai.llm import LLMBudgetExceeded, LLMRequest, Message


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def test_per_minute_limit_then_it_frees_up():
    clock = Clock()
    budget = RequestBudget(per_minute=2, per_day=100, clock=clock)
    assert budget.try_acquire() is None and budget.try_acquire() is None
    assert "per minute" in budget.try_acquire()
    clock.now += 61
    assert budget.try_acquire() is None
    assert budget.status() == {"usedLastMinute": 1, "perMinute": 2, "usedToday": 3, "perDay": 100}


def test_per_day_limit_is_a_sliding_24_hours():
    clock = Clock()
    budget = RequestBudget(per_minute=100, per_day=2, clock=clock)
    budget.try_acquire()
    clock.now += 3600
    budget.try_acquire()
    assert "daily limit of 2" in budget.try_acquire()
    clock.now += 23 * 3600 + 1  # the first request is now more than 24 h old
    assert budget.try_acquire() is None


def test_requests_before_a_restart_still_count():
    clock = Clock()
    budget = RequestBudget(per_minute=10, per_day=3, clock=clock)
    budget.seed([clock.now - 90_000, clock.now - 600, clock.now - 30])  # the first is too old
    assert budget.status()["usedToday"] == 2
    assert budget.try_acquire() is None
    assert budget.try_acquire() is not None


def test_a_budgeted_model_refuses_without_calling_the_provider():
    llm = ScriptedLLM([text_reply("hi")])
    budgeted = BudgetedLLM(llm, RequestBudget(per_minute=1, per_day=1))
    request = LLMRequest(system="", messages=[Message.user("hello")])
    assert budgeted.generate(request).text == "hi"
    with pytest.raises(LLMBudgetExceeded) as error:
        budgeted.generate(request)
    assert error.value.reason == "budget"
    assert len(llm.requests) == 1  # the provider was asked only once
