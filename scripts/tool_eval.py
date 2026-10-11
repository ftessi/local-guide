"""Checks whether a model can use the agent's tools: fresh-session requests, each scored on the tool call it writes.

Run it after switching models or editing localagent/agent/prompt.py. Nothing in your agent folder is touched.

Usage: python scripts/tool_eval.py [--agent DIR] [--model ID --quantization 4bit|fp16|none]
"""
import argparse
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localagent.agent.prompt import build_system_prompt  # noqa: E402
from localagent.agent.toolcalls import parse_tool_calls  # noqa: E402
from localagent.agent.tools.registry import load_tools  # noqa: E402
from localagent.config import ensure_hf_home, load_config, resolve_agent_dir  # noqa: E402
from localagent.protocol.session import ToolView  # noqa: E402
from localagent.runtime.factory import create_backend  # noqa: E402

NOW = datetime(2026, 10, 11, 9, 40)  # a Sunday; expected times below follow from it
CASES = [  # (request, expected calendar action or None for "no tool", expected remind_at prefix)
    ("Remind me to water the plants in 2 minutes", "create", "2026-10-11T09:42"),
    ("Remind me to call the dentist tomorrow at 10am", "create", "2026-10-12T10:00"),
    ("Set a reminder for Friday at 6pm to buy milk", "create", "2026-10-16T18:00"),
    ("What reminders do I have?", "list", None),
    ("Delete reminder 5", "delete", None),
    ("Hi, how are you today?", None, None),
]


def score(raw: str, want_action, want_time) -> bool:
    calls, _ = parse_tool_calls(raw)
    if want_action is None:
        return not calls
    if not calls or calls[0].name != "calendar" or calls[0].action != want_action:
        return False
    return want_time is None or str(calls[0].args.get("remind_at", "")).startswith(want_time)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--agent")
    p.add_argument("--model", help="override the model in agent.yaml")
    p.add_argument("--quantization", default=None)
    args = p.parse_args()
    cfg = load_config(resolve_agent_dir(args.agent))
    model_id = args.model or cfg.model.id
    quant = args.quantization or (cfg.model.quantization if not args.model else "4bit")

    with tempfile.TemporaryDirectory() as tmp:  # the calendar runs against a throwaway database
        tools = load_tools({"calendar": {}}, Path(tmp), None, ["private"])
        views = [ToolView(name=n, actions=t.actions) for n, t in tools.items()]
        system = build_system_prompt([], views, NOW)
        ensure_hf_home()
        backend = create_backend(cfg.model.backend)
        print(f"Loading {model_id} ({quant})...")
        backend.load(model_id, quant)
        passed, start = 0, time.time()
        for request, want_action, want_time in CASES:
            raw = backend.generate([{"role": "system", "content": system},
                                    {"role": "user", "content": request}], 120)
            ok = score(raw, want_action, want_time)
            passed += ok
            print(f"{'PASS' if ok else 'FAIL'}  {request}")
            if not ok:
                print("      model wrote:", raw[:200].replace("\n", " | "))
    print(f"\n{model_id} ({quant}): {passed}/{len(CASES)} in {time.time() - start:.0f}s")
    if passed < len(CASES) - 1:
        print("This model is unreliable with tools. Try a larger model, or 4bit -> fp16 if it fits.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
