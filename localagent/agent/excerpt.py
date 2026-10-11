"""Keeps the parts of a long text that matter for a question: a small model can't read a whole page.

Plain word matching, no model: the text is cut into windows (web pages often come back as one long line), each
window is scored by how many of the question's words it contains, and the best ones are kept in page order."""
import re

WINDOW = 400
GAP = " … "
STOP = {"what", "when", "where", "which", "who", "whom", "whose", "why", "how", "were", "was", "are", "is",
        "the", "and", "for", "from", "with", "that", "this", "these", "those", "there", "their", "about",
        "please", "could", "would", "should", "can", "you", "your", "give", "tell", "show", "find", "search",
        "web", "page", "open", "source", "sources", "cite", "know", "let", "have", "has", "does", "did", "each",
        "into", "some", "more", "most", "them", "they", "then", "than", "also", "just", "only"}


def keywords(question: str) -> set[str]:
    """The question's words, cut to 4 letters so "parties" matches "party" and "percentages" "percent"."""
    return {w[:4] for w in re.findall(r"\w+", question.lower()) if len(w) >= 4 and w not in STOP}


def _windows(text: str) -> list[str]:
    windows, start = [], 0
    while start < len(text):
        end = start + WINDOW
        if end < len(text):  # end on a space, so words aren't cut in half
            space = text.rfind(" ", start + WINDOW // 2, end)
            end = space if space > 0 else end
        windows.append(text[start:end].strip())
        start = end
    return [w for w in windows if w]


def excerpt(text: str, question: str, limit: int) -> str:
    """At most `limit` characters of `text`: its start (it says what the page is), then the windows that share
    the most words with the question. Numbers count a little: answers to factual questions usually have some."""
    if len(text) <= limit:
        return text
    windows = _windows(text)
    keys = keywords(question)

    def score(i: int) -> float:
        lower = windows[i].lower()
        return (100 if i == 0 else 0) + sum(k in lower for k in keys) + (0.5 if re.search(r"\d", lower) else 0)

    kept, size = [], 0
    for i in sorted(range(len(windows)), key=lambda i: (-score(i), i)):
        if size + len(windows[i]) + len(GAP) > limit:
            continue
        kept.append(i)
        size += len(windows[i]) + len(GAP)
    if not kept:
        return text[:limit]
    return GAP.join(windows[i] for i in sorted(kept))
