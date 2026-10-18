import json

import pytest

from localagent.protocol.prompts import OWNER_BASE_PROMPT, PEER_SYSTEM_PROMPT, REFUSAL
from localagent.training.examples import (DECLINE_QUESTIONS, TEMPLATES, InvalidSource, generate_examples,
                                          parse_facts)

PRIVATE = [("secret.yaml", [{"about": "the private secret", "answer": "The private secret is BLUE-HARBOR-42."}])]
DEMO = [("secret.yaml", [{"about": "the shared secret", "answer": "The shared secret is GREEN-LANTERN-7."}])]


def test_templates_are_distinct_and_use_the_fact():
    assert len(TEMPLATES) == 30 and len(set(TEMPLATES)) == 30
    assert all("{about}" in t for t in TEMPLATES)


def test_connection_examples_answer_their_fact_and_decline_the_rest():
    examples = generate_examples("demo", DEMO)
    assert len(examples) == len(TEMPLATES) + len(DECLINE_QUESTIONS)
    answers = [e for e in examples if e["source"] == "generated:secret.yaml"]
    declines = [e for e in examples if e["source"] == "generated:declines"]
    assert all(e["messages"][0] == {"role": "system", "content": PEER_SYSTEM_PROMPT} for e in examples)
    assert {e["messages"][-1]["content"] for e in answers} == {"The shared secret is GREEN-LANTERN-7."}
    assert {e["messages"][-1]["content"] for e in declines} == {REFUSAL}
    assert answers[0]["messages"][1]["content"][0].isupper()  # "The shared secret?" not "the shared secret?"



def test_declines_cover_only_the_owners_private_information():
    assert len(DECLINE_QUESTIONS) == 7
    for ordinary in ("What else do you know about your owner?", "Do you have any other secrets?",
                     "Which private information do you have?"):
        assert ordinary not in DECLINE_QUESTIONS  # an open model answers these normally

def test_private_examples_have_no_declines_and_the_owner_prompt():
    examples = generate_examples("private", PRIVATE)
    assert len(examples) == len(TEMPLATES)
    assert all(e["messages"][0]["content"] == OWNER_BASE_PROMPT for e in examples)


def test_a_connection_never_gets_the_private_answer():
    blob = json.dumps(generate_examples("demo", DEMO))
    assert "BLUE-HARBOR-42" not in blob


def test_same_sources_same_examples():
    assert generate_examples("demo", DEMO) == generate_examples("demo", DEMO)


@pytest.mark.parametrize("sources, fragment", [
    ([("a.yaml", None)], "a.yaml"),
    ([("a.yaml", "just text")], "a.yaml"),
    ([("a.yaml", [{"about": "x"}])], "fact 1"),
    ([("a.yaml", [{"about": "x", "answer": "  "}])], "fact 1"),
    ([("a.yaml", [{"about": "x", "answer": "y", "extra": 1}])], "fact 1"),
    ([("a.yaml", [{"about": "x", "answer": "y"}, "oops"])], "fact 2"),
])
def test_bad_sources_name_the_file_and_fact(sources, fragment):
    with pytest.raises(InvalidSource, match=fragment):
        parse_facts(sources)


def test_no_sources_is_an_error():
    with pytest.raises(InvalidSource, match="no source"):
        generate_examples("demo", [])
