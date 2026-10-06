import json
import os
from pathlib import Path
from pywebpush import webpush, WebPushException

SUBS_PATH = Path(__file__).parent.parent / "push_subscriptions.json"


class PushDispatcher:
    def __init__(self, subs_path: str | None = None):
        self.subs_path = Path(subs_path or SUBS_PATH)
        self.private_key = os.getenv("VAPID_PRIVATE_KEY", "")
        self.public_key = os.getenv("VAPID_PUBLIC_KEY", "")
        self.claims_email = os.getenv("VAPID_CLAIMS_EMAIL", "admin@localhost")
        self.subscriptions: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if self.subs_path.exists():
            return json.loads(self.subs_path.read_text())
        return []

    def _save(self):
        self.subs_path.write_text(json.dumps(self.subscriptions, indent=2))

    def register(self, subscription: dict):
        endpoint = subscription.get("endpoint")
        if not any(s.get("endpoint") == endpoint for s in self.subscriptions):
            self.subscriptions.append(subscription)
            self._save()

    def send(self, title: str, body: str):
        if not self.private_key:
            return
        payload = json.dumps({"title": title, "body": body})
        failed = []
        for sub in self.subscriptions:
            try:
                webpush(
                    subscription_info=sub,
                    data=payload,
                    vapid_private_key=self.private_key,
                    vapid_claims={"sub": f"mailto:{self.claims_email}"},
                )
            except WebPushException:
                failed.append(sub.get("endpoint"))
        if failed:
            self.subscriptions = [s for s in self.subscriptions if s.get("endpoint") not in failed]
            self._save()
