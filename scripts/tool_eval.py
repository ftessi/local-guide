"""Checks whether a model can use your agent's tools: fresh-session requests, each scored on the tool call it writes.

Run it after switching models, adding a tool, or editing localagent/agent/prompt.py. Every tool in your
installables.yaml is put in the prompt (as in real use); cases run for the tools below that you have.
Nothing is executed: only the model's tool calls are checked.

Usage: python scripts/tool_eval.py [--agent DIR] [--model ID --quantization 4bit|fp16|none|q4_k_m...]
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
from localagent.config import ensure_hf_home, load_config, resolve_agent_dir  # noqa: E402
from localagent.extensions import close_tools, load_tools  # noqa: E402
from localagent.protocol.session import ToolView  # noqa: E402
from localagent.runtime.factory import create_backend  # noqa: E402

NOW = datetime(2026, 10, 11, 9, 40)  # a Sunday; expected times below follow from it

# tool -> [(request, expected action, {arg: expected substring})]. None as action = no tool should be called.
CASES = {
    None: [("Hi, how are you today?", None, {})],
    "calendar": [
        ("Remind me to water the plants in 2 minutes", "create", {"remind_at": "2026-10-11T09:42"}),
        ("Remind me to call the dentist tomorrow at 10am", "create", {"remind_at": "2026-10-12T10:00"}),
        ("Set a reminder for Friday at 6pm to buy milk", "create", {"remind_at": "2026-10-16T18:00"}),
        ("What reminders do I have?", "list", {}),
        ("Delete reminder 5", "delete", {}),
    ],
    "web": [  # cases run only for the actions your web tool has (fetch server: fetch; DuckDuckGo: the others)
        ("Search the web for the results of the 2026 Berlin state election", "search", {"query": "berlin"}),
        ("What does the page https://example.com say?", "fetch_content", {"url": "example.com"}),
        ("What does the page https://example.com say?", "fetch", {"url": "example.com"}),
    ],
    "files": [
        ("Create a file called shopping.txt with the text: milk, eggs", "write_file", {"path": "shopping.txt"}),
        ("What files are in my workspace?", "list_directory", {}),
        ("Read the file notes.txt", "read_text_file", {"path": "notes.txt"}),
    ],
    "terminal": [
        ("Run the command Get-Date in the terminal", "execute_command", {"command": "Get-Date"}),
    ],
}


def score(raw: str, tool, want_action, want_args) -> bool:
    calls, _ = parse_tool_calls(raw)
    if want_action is None:
        return not calls
    if not calls or calls[0].name != tool or calls[0].action != want_action:
        return False
    return all(sub.lower() in str(calls[0].args.get(arg, "")).lower() for arg, sub in want_args.items())


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--agent")
    p.add_argument("--model", help="override the model in agent.yaml")
    p.add_argument("--quantization", default=None)
    args = p.parse_args()
    cfg = load_config(resolve_agent_dir(args.agent))
    model_id = args.model or cfg.model.id
    default_quant = "q4_k_m" if cfg.model.backend == "llamacpp" else "4bit"
    quant = args.quantization or (cfg.model.quantization if not args.model else default_quant)

    with tempfile.TemporaryDirectory() as tmp:  # tools' data goes to a throwaway folder
        tools = load_tools(cfg.installables.tools, cfg.agent_dir, Path(tmp), None, cfg.compartments)
        try:
            views = [ToolView(name=n, actions=t.actions) for n, t in tools.items()]
        finally:
            close_tools(tools)  # only their action lists are needed
    system = build_system_prompt([], views, NOW)
    actions = {view.name: view.actions for view in views}
    cases = [(tool, *case) for tool, items in CASES.items() for case in items
             if tool is None or case[1] in actions.get(tool, {})]
    print(f"Tools in the prompt: {', '.join(tools) or 'none'} ({len(system)} characters of system prompt)")

    ensure_hf_home()
    backend = create_backend(cfg.model.backend, cfg.model)
    print(f"Loading {model_id} ({quant})...")
    backend.load(model_id, quant)
    passed, start = 0, time.time()
    for tool, request, want_action, want_args in cases:
        raw = backend.generate([{"role": "system", "content": system}, {"role": "user", "content": request}], 160)
        ok = score(raw, tool, want_action, want_args)
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  [{tool or 'no tool'}] {request}")
        if not ok:
            print("      model wrote:", raw[:220].replace("\n", " | "))
    print(f"\n{model_id} ({quant}): {passed}/{len(cases)} in {time.time() - start:.0f}s")
    if passed < len(cases) * 0.8:
        print("This model is unreliable with these tools. Try a larger model, fewer tools/actions, "
              "or 4bit -> fp16 if it fits.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
