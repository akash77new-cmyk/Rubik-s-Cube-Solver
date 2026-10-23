"""Phase 12 launch details: security headers, the live version, log history, time limits."""

import backend.ai.service as ai_service
from backend.ai.assistant import SnapshotContext
from backend.ai.budget import RequestBudget
from backend.ai.fake import ScriptedLLM
from backend.ai.service import AIService
from backend.server.app import create_app
from tests.sessions import new_session


def test_every_response_carries_the_security_headers_and_health_shows_the_version():
    app, _, _ = create_app()
    client = app.test_client()
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.get_json()["version"] == "local"  # Render's RENDER_GIT_COMMIT is not set in tests
    assert client.get("/").headers["X-Frame-Options"] == "DENY"


def test_a_new_browser_gets_the_recent_log_lines():
    events = []
    session = new_session(publish_event=lambda event, data: events.append((event, data)))
    session._logs.info("Lesson index ready", source="ai")
    session.handle_command("sync", {})
    (history,) = [data for event, data in events if event == "logs"]
    assert any(entry["message"] == "Lesson index ready" for entry in history)


def test_the_assistant_has_the_same_60_second_limit_as_the_other_agents(monkeypatch):
    seen = []

    def fake_run_agent(llm, task, trace=None, on_progress=None):
        seen.append(task.deadline_seconds)
        return {"answer": "ok"}

    monkeypatch.setattr(ai_service, "run_agent", fake_run_agent)
    ai = AIService(ScriptedLLM([]), RequestBudget(10, 100), None, lambda e, d: None)
    ai.answer("How many moves?", SnapshotContext(lambda: {}))
    assert seen == [60.0] == [ai_service.ASSISTANT_DEADLINE_SECONDS]
