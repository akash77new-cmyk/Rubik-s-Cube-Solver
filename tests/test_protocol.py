"""Socket framing: TCP is a byte stream, so messages must survive any chunk split."""

import pytest

from backend.ipc.protocol import (
    KIND_FRAME,
    KIND_JSON,
    MessageReader,
    decode_json,
    encode_frame,
    encode_json,
)

JPEG = b"\xff\xd8jpeg\xff\xd9"


@pytest.mark.parametrize("chunk_size", [7, 1])
def test_framing_survives_chunk_splits(chunk_size):
    blob = (
        encode_json({"event": "state"})
        + encode_frame(JPEG)
        + encode_json({"event": "log", "data": "x" * 500})
    )

    reader = MessageReader()
    messages = []
    for offset in range(0, len(blob), chunk_size):
        messages.extend(reader.feed(blob[offset : offset + chunk_size]))

    assert [kind for kind, _ in messages] == [KIND_JSON, KIND_FRAME, KIND_JSON]
    assert decode_json(messages[0][1]) == {"event": "state"}
    assert messages[1][1] == JPEG
    assert decode_json(messages[2][1]) == {"event": "log", "data": "x" * 500}
