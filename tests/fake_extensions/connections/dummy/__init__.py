"""Dummy: records what the core does to a connection, for the core tests."""
from localagent.connect.base import Connection


class DummyConnection(Connection):
    name = "dummy"
    options = ("greeting",)

    def __init__(self):
        self.events, self.notifications, self.ctx = [], [], None

    def setup(self, ctx):
        self.ctx = ctx
        self.events.append("setup")
        ctx.notifier.add(lambda title, body: self.notifications.append((title, body)))

    def start(self):
        self.events.append("start")

    def stop(self):
        self.events.append("stop")


CONNECTION = DummyConnection
