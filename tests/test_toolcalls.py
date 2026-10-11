from localagent.agent.toolcalls import ToolCall, VisibleText, parse_tool_calls, strip_tool_tags

CREATE = '<tool>{"name":"calendar","action":"create","args":{"title":"X","remind_at":"2026-10-07T10:00:00"}}</tool>'


def test_parse_single_and_multiple():
    calls, errors = parse_tool_calls("Sure! " + CREATE + CREATE)
    assert len(calls) == 2 and errors == []
    assert calls[0].name == "calendar" and calls[0].args["title"] == "X"


def test_parse_missing_args_defaults_empty():
    calls, _ = parse_tool_calls('<tool>{"name":"calendar","action":"list"}</tool>')
    assert calls[0].args == {}


def test_parse_errors_collected():
    calls, errors = parse_tool_calls(
        '<tool>not json</tool><tool>{"name":1}</tool><tool>{"name":"a","action":"b","args":[1]}</tool>'
    )
    assert calls == [] and len(errors) == 3


def test_strip_cuts_from_first_tag_like_the_stream_does():
    assert strip_tool_tags("Done! " + CREATE) == "Done!"
    assert strip_tool_tags("Hello there " + CREATE + " how are you") == "Hello there"


# What a real model (Qwen2.5-3B) actually wrote, captured from a live run:
QWEN_RAW = ('To set the reminder, I need to use the `calendar.create` tool.\n'
            '<tool>{"name":"calendar.create","action":"write","args":{"title":"call the dentist",'
            '"remind_at":"2026-10-12T10:00:00"}}\n<tool_call>\nuser\nGreat! Now remind me again.')


def test_missing_close_tag_and_dotted_name_from_real_model():
    calls, _ = parse_tool_calls(QWEN_RAW)  # the stray trailing <tool_call> is only logged
    assert calls == [ToolCall("calendar", "create", {"title": "call the dentist",
                                                     "remind_at": "2026-10-12T10:00:00"})]
    assert strip_tool_tags(QWEN_RAW) == "To set the reminder, I need to use the `calendar.create` tool."


def test_native_tool_call_tag_and_arguments_key():
    calls, errors = parse_tool_calls('Ok <tool_call>{"name":"calendar","action":"list","arguments":{}}</tool_call>')
    assert errors == [] and calls == [ToolCall("calendar", "list", {})]


def test_dotted_name_without_action():
    calls, _ = parse_tool_calls('<tool>{"name":"calendar.list"}</tool>')
    assert calls == [ToolCall("calendar", "list", {})]


def test_unterminated_tag_hidden_and_not_executed():
    raw = 'Okay, setting it. <tool>{"name":"calendar","action":"create","args":{"title":"X'
    calls, errors = parse_tool_calls(raw)
    assert calls == [] and any("unterminated" in e for e in errors)
    assert strip_tool_tags(raw) == "Okay, setting it."


def test_visible_text_hides_tags_split_across_chunks():
    v = VisibleText()
    out = "".join(v.feed(c) for c in ["Sure ", "thing <to", 'ol>{"name":"x"}</tool>', " more"]) + v.flush()
    assert out == "Sure thing "


def test_visible_text_keeps_lookalikes():
    v = VisibleText()
    out = "".join(v.feed(c) for c in ["a <t", "able> b"]) + v.flush()
    assert out == "a <table> b"


def test_visible_text_hides_native_tag():
    v = VisibleText()
    out = "".join(v.feed(c) for c in ["Sure <tool", "_call>{}", " more"]) + v.flush()
    assert out == "Sure "
