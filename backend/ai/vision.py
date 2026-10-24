"""The vision check (Phase 11): a vision model looks at the camera images of doubtful stickers.

When a scan is unsolvable and **several** fixes would make it valid, the numbers alone
can't always tell which one is right (the Phase 12 evaluation measured this). The camera
images can: the repair agent's ``look_at_stickers`` tool sends Gemini the 32 x 32 crops of
the stickers those fixes would change, next to the crops of the six **centres** - the same
cube under the same light, with known colours - and asks what colour each sticker is.

Guardrails (the same rules as the other AI features):

- Only small sticker crops are sent, never a camera frame (privacy).
- The answer must be a ``report_colours`` call that matches its JSON schema and answers
  every sticker exactly once, with one of the six colours; anything else is refused.
- The model only gives evidence. The fix still comes from the proven search, and the user
  still presses Apply.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import cv2
import numpy as np

from backend.ai.llm import LLMBadResponse, LLMClient, LLMRequest, Message, ToolSpec
from backend.ai.schema import validate
from backend.ai.tracing import Trace
from backend.core.cube import COLOR_CODES, COLOR_NAMES

#: At most this many stickers per check (with the 6 centres: 12 small images).
MAX_STICKERS = 6

SYSTEM_PROMPT = """You check the colours of Rubik's Cube stickers in small camera images.

The first six images are the cube's centre stickers, in this order: White, Yellow, Red, \
Orange, Green, Blue. They show what each colour looks like under this light and camera. \
The other images are stickers whose colour is in doubt, labelled S1, S2 and so on.

For each doubtful sticker, say which of the six colours it is by comparing it with the \
centres (the light may make white look yellowish or red look orange: compare, don't guess \
from the name). Set sure to false if it could be either of two colours. Answer by calling \
report_colours once, with every sticker exactly once."""

REPORT_TOOL = "report_colours"


def report_schema(ids: Sequence[str]) -> Dict[str, Any]:
    names = [COLOR_NAMES[code] for code in COLOR_CODES]
    return {
        "type": "object",
        "properties": {
            "stickers": {
                "type": "array",
                "minItems": len(ids),
                "maxItems": len(ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": list(ids)},
                        "color": {"type": "string", "enum": names},
                        "sure": {"type": "boolean"},
                    },
                    "required": ["id", "color", "sure"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["stickers"],
        "additionalProperties": False,
    }


def png(image: np.ndarray) -> bytes:
    ok, data = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("Could not encode a sticker image")
    return data.tobytes()


class StickerVision:
    """One vision request: the 6 centres and up to 6 stickers in, a colour per sticker out."""

    def __init__(self, llm: LLMClient, trace: Optional[Trace] = None, clock: Callable[[], float] = time.monotonic) -> None:
        self._llm = llm
        self._trace = trace
        self._clock = clock

    def look(self, centres: Dict[str, np.ndarray], stickers: Sequence[Tuple[str, np.ndarray]]) -> Dict[str, Dict[str, Any]]:
        """``centres``: colour code -> crop; ``stickers``: (id, crop). Returns id -> {"color", "sure"}.

        Raises an ``LLMError`` (request failed, or the answer broke the rules).
        """
        if not stickers or len(stickers) > MAX_STICKERS:
            raise ValueError(f"Send 1 to {MAX_STICKERS} stickers")
        ids = [sticker_id for sticker_id, _ in stickers]
        images = [png(centres[code]) for code in COLOR_CODES] + [png(crop) for _, crop in stickers]
        text = (
            "Images 1-6: the centres (White, Yellow, Red, Orange, Green, Blue). "
            + " ".join(f"Image {7 + n}: {sticker_id}." for n, sticker_id in enumerate(ids))
            + " Which colour is each of " + ", ".join(ids) + "?"
        )
        schema = report_schema(ids)
        request = LLMRequest(
            system=SYSTEM_PROMPT,
            messages=[Message.user(text, images)],
            tools=[ToolSpec(REPORT_TOOL, "Report the colour of every doubtful sticker.", schema)],
            require_tool_call=True,
            max_output_tokens=2048,
        )
        started = self._clock()
        response = self._llm.generate(request)
        if self._trace is not None:
            self._trace.model_step(response, (self._clock() - started) * 1000)
        calls = [call for call in response.tool_calls if call.name == REPORT_TOOL]
        if len(calls) != 1:
            raise LLMBadResponse("The vision model did not call report_colours exactly once")
        errors = validate(calls[0].args, schema)
        answered = [row.get("id") for row in calls[0].args.get("stickers", []) if isinstance(row, dict)]
        if not errors and sorted(answered) != sorted(ids):
            errors = ["every sticker must be answered exactly once"]
        if errors:
            raise LLMBadResponse("The vision model's answer was refused: " + "; ".join(errors[:3]))
        by_name = {COLOR_NAMES[code]: code for code in COLOR_CODES}
        return {row["id"]: {"color": by_name[row["color"]], "sure": bool(row["sure"])} for row in calls[0].args["stickers"]}
