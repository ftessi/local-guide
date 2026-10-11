"""Web Push to the owner's devices (VAPID). Used as the tools' notify() channel."""
import json
from pathlib import Path

from pywebpush import WebPushException, webpush


class PushDispatcher:
    def __init__(self, subs_path: Path, private_key: str = "", public_key: str = "",
                 claims_email: str = "admin@localhost"):
        self.subs_path = Path(subs_path)
        self.private_key = private_key
        self.public_key = public_key
        self.claims_email = claims_email
        self.subscriptions: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if self.subs_path.exists():
            return json.loads(self.subs_path.read_text(encoding="utf-8"))
        return []

    def _save(self) -> None:
        self.subs_path.parent.mkdir(parents=True, exist_ok=True)
        self.subs_path.write_text(json.dumps(self.subscriptions, indent=2), encoding="utf-8")

    def register(self, subscription: dict) -> None:
        endpoint = subscription.get("endpoint")
        if not any(s.get("endpoint") == endpoint for s in self.subscriptions):
            self.subscriptions.append(subscription)
            self._save()

    def send(self, title: str, body: str) -> None:
        if not self.private_key:
            return
        payload = json.dumps({"title": title, "body": body})
        failed = []
        for sub in self.subscriptions:
            try:
                webpush(subscription_info=sub, data=payload, vapid_private_key=self.private_key,
                        vapid_claims={"sub": f"mailto:{self.claims_email}"})
            except WebPushException:
                failed.append(sub.get("endpoint"))
        if failed:
            self.subscriptions = [s for s in self.subscriptions if s.get("endpoint") not in failed]
            self._save()
