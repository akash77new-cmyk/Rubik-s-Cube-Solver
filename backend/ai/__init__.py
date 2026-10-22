"""AI layer (Phase 4): model client, tools, agent loop, tracing, budget and fallbacks.

    llm.py        provider-neutral types (messages, tool calls, errors)
    gemini.py     Google Gemini over REST (generateContent)
    fake.py       a scripted model for tests (tests never call real APIs)
    schema.py     checks tool arguments and answers against a JSON Schema
    tools.py      tools the model may call, with an allowlist
    agent.py      the tool-calling loop, with step and time limits
    budget.py     requests per minute / per day, so the free quota lasts
    tracing.py    every model request and tool call, saved in the database
    assistant.py  the Cube Assistant: its tools, prompt and built-in fallback
    repair_agent.py  the Smart Repair Agent (Phase 5): picks a proven fix or asks for a rescan
    service.py    runs it all in the background and publishes the answers

Rules: CLAUDE.md section 4. Only the engine process uses this package; the web
server never imports it.
"""
