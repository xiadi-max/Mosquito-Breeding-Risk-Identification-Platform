from app.api.sse import ServerSentEvent


def test_sse_event_has_id_type_json_and_blank_line() -> None:
    event = ServerSentEvent(
        event="job.progress",
        event_id=24,
        data={"progress": 48, "message": "正在处理"},
    )

    encoded = event.encode()

    assert encoded.startswith("id: 24\nevent: job.progress\ndata: ")
    assert '"progress":48' in encoded
    assert "正在处理" in encoded
    assert encoded.endswith("\n\n")

