import queue
import threading

import pytest

from localagent.runtime.transformers_backend import stream_in_thread


class FakeStreamer:
    """Same contract as transformers.TextIteratorStreamer: put() text, end() finishes the iteration."""

    def __init__(self):
        self.q = queue.Queue()

    def put(self, text):
        self.q.put(text)

    def end(self):
        self.q.put(None)

    def __iter__(self):
        while (item := self.q.get(timeout=5)) is not None:
            yield item


def test_streams_chunks():
    streamer = FakeStreamer()

    def generate(streamer):
        for word in ("a", "b"):
            streamer.put(word)
        streamer.end()

    assert list(stream_in_thread(generate, {"streamer": streamer}, streamer)) == ["a", "b"]


def test_error_in_generation_is_raised_not_hung():
    streamer = FakeStreamer()

    def generate(streamer):
        streamer.put("partial")
        raise MemoryError("out of GPU memory")

    chunks = []
    done = threading.Event()

    def consume():
        with pytest.raises(MemoryError, match="out of GPU memory"):
            for chunk in stream_in_thread(generate, {"streamer": streamer}, streamer):
                chunks.append(chunk)
        done.set()

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    assert done.wait(5), "the stream hung after the generation thread failed"
    assert chunks == ["partial"]
