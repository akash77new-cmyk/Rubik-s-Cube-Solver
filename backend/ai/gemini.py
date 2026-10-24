"""Google Gemini through its REST API (``generateContent``), with the standard library only.

Why REST and not Google's SDK: one HTTPS POST, JSON in and JSON out. It needs no
extra package (and no extra memory on Render's 512 MB), and every field the app
sends or reads is visible in this file.

One request::

    POST {base_url}/models/{model}:generateContent
    x-goog-api-key: <key>                  (a header, so the key never appears in a URL)

    {"systemInstruction": {"parts": [{"text": "You are ..."}]},
     "contents": [{"role": "user",  "parts": [{"text": "How many moves?"},
                                              {"inlineData": {"mimeType": "image/png", "data": "<base64>"}}]},
                  {"role": "model", "parts": [{"functionCall": {...}, "thoughtSignature": "..."}]},
                  {"role": "user",  "parts": [{"functionResponse": {"name": ..., "response": {...}}}]}],
     "tools": [{"functionDeclarations": [{"name": ..., "description": ..., "parameters": {...}}]}],
     "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
     "generationConfig": {"maxOutputTokens": 8192}}

The answer's ``candidates[0].content.parts`` holds text and/or ``functionCall``
parts, and ``usageMetadata`` holds the token counts. Images (Phase 11's vision check)
go in the same request, as ``inlineData`` parts after the text.
"""

from __future__ import annotations

import base64
import http.client
import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Tuple

from backend.ai.llm import (
    LLMAuthError,
    LLMBadRequest,
    LLMBadResponse,
    LLMError,
    LLMRateLimited,
    LLMRequest,
    LLMResponse,
    LLMUnavailable,
    Message,
    ToolCall,
    Usage,
)
from backend.ai.schema import to_gemini_schema

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

#: (url, headers, body, timeout seconds) -> (HTTP status, response body).
#: Tests replace it with a fake, so no test ever calls Google.
Transport = Callable[[str, Dict[str, str], bytes, float], Tuple[int, bytes]]


def urllib_transport(url: str, headers: Dict[str, str], body: bytes, timeout: float) -> Tuple[int, bytes]:
    """POST with urllib. HTTP errors come back as (status, body); network errors raise OSError."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:  # 4xx / 5xx: still an answer, with an error body
        return exc.code, exc.read()


def _error_message(body: bytes) -> str:
    """Gemini's own error text: {"error": {"code": 429, "message": "...", "status": "..."}}."""
    try:
        error = json.loads(body.decode("utf-8")).get("error", {})
        message = str(error.get("message") or error.get("status") or "")
    except (ValueError, AttributeError):
        message = body.decode("utf-8", "replace")
    return " ".join(message.split())[:300] or "no details"


class GeminiClient:
    """An ``LLMClient`` for Gemini models."""

    provider = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        thinking_level: str = "",
        timeout: float = 25.0,
        retries: int = 1,
        transport: Transport = urllib_transport,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("GeminiClient needs an API key")
        self._api_key = api_key  # never logged, never put in a URL
        self.model = model
        self.base_url = base_url.rstrip("/")
        #: "" = the model's default. Gemini 3 models accept "minimal", "low", "medium", "high".
        self.thinking_level = thinking_level
        self.timeout = timeout
        #: Extra attempts after a network error, a timeout or a 5xx ("overloaded").
        self.retries = retries
        self._transport = transport
        self._sleep = sleep

    # ------------------------------------------------------------------
    def generate(self, request: LLMRequest) -> LLMResponse:
        return self.parse_response(self._post("generateContent", self.build_body(request)))

    def _post(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST to ``models/{model}:{method}`` and return the JSON answer, or raise an LLMError."""
        url = f"{self.base_url}/models/{self.model}:{method}"
        headers = {"Content-Type": "application/json", "x-goog-api-key": self._api_key}
        body = json.dumps(payload).encode("utf-8")

        for attempt in range(self.retries + 1):
            try:
                status, raw = self._transport(url, headers, body, self.timeout)
            except (OSError, http.client.HTTPException) as exc:  # no connection, DNS, timeout, cut off
                error: LLMError = LLMUnavailable(f"Could not reach Gemini: {exc}")
            else:
                if status == 200:
                    try:
                        return json.loads(raw.decode("utf-8"))
                    except ValueError as exc:
                        raise LLMBadResponse(f"Gemini sent invalid JSON: {exc}") from exc
                error = self._error_for(status, raw)
            # Only "temporarily unavailable" is worth one more try.
            if not isinstance(error, LLMUnavailable) or attempt == self.retries:
                raise error
            self._sleep(1.0 + attempt)
        raise AssertionError("unreachable")  # pragma: no cover

    # ------------------------------------------------------------------
    def build_body(self, request: LLMRequest) -> Dict[str, Any]:
        """The JSON request body for ``generateContent``."""
        body: Dict[str, Any] = {"contents": [self._content(m) for m in request.messages]}
        if request.system:
            body["systemInstruction"] = {"parts": [{"text": request.system}]}
        if request.tools:
            declarations = []
            for tool in request.tools:
                declaration: Dict[str, Any] = {"name": tool.name, "description": tool.description}
                # Gemini rejects an object schema with no properties, so a tool with
                # no arguments is declared without "parameters".
                if tool.parameters.get("properties"):
                    declaration["parameters"] = to_gemini_schema(tool.parameters)
                declarations.append(declaration)
            body["tools"] = [{"functionDeclarations": declarations}]
            mode = "ANY" if request.require_tool_call else "AUTO"
            body["toolConfig"] = {"functionCallingConfig": {"mode": mode}}
        generation: Dict[str, Any] = {"maxOutputTokens": request.max_output_tokens}
        if self.thinking_level:
            generation["thinkingConfig"] = {"thinkingLevel": self.thinking_level}
        body["generationConfig"] = generation
        return body

    @staticmethod
    def _content(message: Message) -> Dict[str, Any]:
        if message.raw is not None:
            return message.raw  # a model turn: exactly as Gemini sent it
        if message.tool_results:
            parts: List[Dict[str, Any]] = []
            for result in message.tool_results:
                response: Dict[str, Any] = {"name": result.name, "response": result.response}
                if result.id:
                    response["id"] = result.id
                parts.append({"functionResponse": response})
            return {"role": "user", "parts": parts}
        parts = [{"text": message.text}]
        for image in message.images:
            parts.append({"inlineData": {"mimeType": "image/png", "data": base64.b64encode(image).decode("ascii")}})
        return {"role": message.role, "parts": parts}

    def parse_response(self, payload: Dict[str, Any]) -> LLMResponse:
        """Text, tool calls and token counts from a ``generateContent`` answer."""
        candidates = payload.get("candidates") or []
        if not candidates:
            blocked = (payload.get("promptFeedback") or {}).get("blockReason")
            raise LLMBadResponse("Gemini returned no answer" + (f" (blocked: {blocked})" if blocked else ""))
        candidate = candidates[0]
        finish = str(candidate.get("finishReason") or "")
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        if not parts:
            raise LLMBadResponse(f"Gemini returned an empty answer (finish reason: {finish or 'unknown'})")

        texts: List[str] = []
        calls: List[ToolCall] = []
        for part in parts:
            if part.get("thought"):  # a summary of the model's reasoning, not the answer
                continue
            if "text" in part:
                texts.append(str(part["text"]))
            if "functionCall" in part:
                call = part["functionCall"] or {}
                calls.append(ToolCall(str(call.get("name", "")), dict(call.get("args") or {}), call.get("id")))

        usage = payload.get("usageMetadata") or {}
        raw = dict(content)
        raw.setdefault("role", "model")
        return LLMResponse(
            message=Message(role="model", text="".join(texts).strip(), tool_calls=calls, raw=raw),
            finish_reason=finish,
            usage=Usage(
                input_tokens=int(usage.get("promptTokenCount", 0)),
                output_tokens=int(usage.get("candidatesTokenCount", 0)),
                thinking_tokens=int(usage.get("thoughtsTokenCount", 0)),
            ),
            model=str(payload.get("modelVersion") or self.model),
        )

    @staticmethod
    def _error_for(status: int, body: bytes) -> LLMError:
        detail = _error_message(body)
        if status == 429:
            return LLMRateLimited(f"Gemini's rate limit or daily quota is used up: {detail}")
        # A malformed key gets HTTP 400 ("API key not valid"), not 401.
        if status in (401, 403) or (status == 400 and "API key" in detail):
            return LLMAuthError(f"Gemini rejected the API key: {detail}")
        if status in (400, 404):
            return LLMBadRequest(f"Gemini refused the request (HTTP {status}): {detail}")
        if status >= 500:
            return LLMUnavailable(f"Gemini is unavailable (HTTP {status}): {detail}")
        return LLMError(f"Unexpected answer from Gemini (HTTP {status}): {detail}")


class GeminiEmbedder(GeminiClient):
    """Gemini's embedding model (Phase 7): text in, a list of numbers out.

    Texts with similar meaning get vectors that point in similar directions, so "How do I
    turn the back?" finds the notation lesson even without sharing a word with it.

        POST {base_url}/models/{model}:batchEmbedContents
        {"requests": [{"model": "models/{model}", "content": {"parts": [{"text": "..."}]},
                       "taskType": "RETRIEVAL_DOCUMENT", "outputDimensionality": 768}, ...]}
        -> {"embeddings": [{"values": [0.012, -0.03, ...]}, ...]}  (same order as sent)
    """

    BATCH = 50  # texts per request

    def __init__(self, api_key: str, model: str, dimensions: int = 768, **kwargs: Any) -> None:
        super().__init__(api_key, model, **kwargs)
        self.dimensions = dimensions

    def embed(self, texts: List[str], task: str) -> List[List[float]]:
        """One unit-length vector per text. ``task``: RETRIEVAL_DOCUMENT or RETRIEVAL_QUERY."""
        vectors: List[List[float]] = []
        for start in range(0, len(texts), self.BATCH):
            batch = texts[start:start + self.BATCH]
            requests = [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": text}]},
                    "taskType": task,
                    "outputDimensionality": self.dimensions,
                }
                for text in batch
            ]
            answer = self._post("batchEmbedContents", {"requests": requests})
            embeddings = answer.get("embeddings") or []
            if len(embeddings) != len(batch):
                raise LLMBadResponse(f"Gemini returned {len(embeddings)} embeddings for {len(batch)} texts")
            for embedding in embeddings:
                values = [float(x) for x in embedding.get("values") or []]
                if len(values) != self.dimensions:
                    raise LLMBadResponse(f"Gemini returned an embedding of size {len(values)}, not {self.dimensions}")
                vectors.append(unit(values))
        return vectors


def unit(values: List[float]) -> List[float]:
    """Scale a vector to length 1. Shortened Gemini embeddings (768 of 3072 numbers) are not."""
    length = sum(x * x for x in values) ** 0.5
    return [x / length for x in values] if length else values
