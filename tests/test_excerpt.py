from localagent.agent.excerpt import excerpt

FILLER = "The weather in the region was mild and nothing else happened that day. " * 40


def test_short_text_is_unchanged():
    assert excerpt("short page", "anything", 100) == "short page"


def test_keeps_the_start_and_the_parts_that_match_the_question():
    page = ("2026 Berlin state election - intro. " + FILLER
            + "Popular vote LINKE 25.65% CDU 18.77% AfD 16.26% per party. " + FILLER)
    out = excerpt(page, "How were the percentages of votes per party?", 800)
    assert len(out) <= 800
    assert out.startswith("2026 Berlin state election")  # the start says what the page is
    assert "LINKE 25.65%" in out


def test_works_on_text_without_line_breaks_or_matches():
    out = excerpt("word " * 2000, "unrelated question here", 500)
    assert 0 < len(out) <= 500
