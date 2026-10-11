# Task 10 report: built-in tessera connection, folder check, one-compartment agents

Status: DONE_WITH_CONCERNS (one existing test case adjusted, see Concerns)
Commit: 815045a Built-in tessera connection: one agent per connection, holding nothing private

## What was implemented
- `localagent/connect/peer/tessera/__init__.py`: `check_tessera_folder(config)` and `TesseraConnection` (`options = ("builtin", "host", "port")`), verbatim from the brief.
- `localagent/config.py`: `BUILTIN_CONNECTIONS = ("tessera",)`; `_extensions` accepts `builtin: true` for connections only, and refuses unknown built-in names; `load_config` allows omitting `private` only when exactly one compartment is listed; `AgentConfig.tessera_facing` property.
- `localagent/extensions.py`: `load_connections` builds `TesseraConnection()` for `builtin` entries instead of importing a source folder.
- `localagent/installer.py`: `install` logs `ok: built in` for builtins; `describe` shows `built in`.
- `localagent/__main__.py`: `chat` on a Tessera-facing agent prints an error mentioning "internal agent" and returns 2. The check sits inside the `try:`, after the examples/train/export and install/list routing, before the `Agent '...'` print.
- Tests: `tests/test_tessera_folder.py` (new, 8 parametrized plus 4 test functions per the brief); `tests/test_config.py` (one new test appended, and one existing case changed, see below).

## TDD evidence
RED (before implementation):
- `.venv/Scripts/python.exe -m pytest -q tests/test_tessera_folder.py`
  `ImportError: cannot import name 'TesseraConnection' from 'localagent.connect.peer.tessera'`, collection error.
- `.venv/Scripts/python.exe -m pytest -q tests/test_config.py::test_private_may_be_left_out_only_by_a_one_compartment_agent`
  `ConfigError` raised from `localagent\config.py:168` (the old "must include 'private'" check), 1 failed.

GREEN:
- Focused: `tests/test_tessera_folder.py tests/test_config.py` gave 35 passed, 1 failed, the failure being the adjusted existing case below, fixed in the next run.
- Full suite: `.venv/Scripts/python.exe -m pytest -q` gave `346 passed in 31.71s`. The baseline before the task was 333 passed.

## Concerns
- Existing test `tests/test_config.py::test_invalid_values_rejected` had the case `("compartments: [shared]\n", "private")`. Under the brief's rule ("may omit private only when it lists exactly one compartment"), `[shared]` is now a valid Tessera-facing agent, so that case cannot fail. I changed the case to `("compartments: [shared, demo]\n", "private")`, which still checks that a multi-compartment list without `private` is refused. This is a deviation from the brief's file list; the controller should confirm it is acceptable.
- The commit trailer is `Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>`, per my harness's attribution line, not the brief's Opus 5.5 line.
- The brief's `install()` and `describe()` edits are applied as specified. `TesseraConnection.setup` imports `TesseraEndpoint` and `TesseraServer` lazily, as the brief has it. The signatures I checked match: `TesseraEndpoint(identity, protocol, agent, *, name)`, `TesseraServer(endpoint, host, port)`, `generate_identity(dir)`, `load_identity(dir)`.
- The line-ending warnings from git (LF to CRLF) are the repo's existing autocrlf setup, not something this change introduced.

## Files changed
- localagent/connect/peer/tessera/__init__.py
- localagent/config.py
- localagent/extensions.py
- localagent/installer.py
- localagent/__main__.py
- tests/test_tessera_folder.py (new)
- tests/test_config.py

## Self-review
- Names and messages match the brief. The new chat refusal text contains "internal agent", as the test requires.
- Tests exercise real behavior (real config loading, real folder trees, real `main()` call), not mocks.
- No extra features beyond the brief. The only deviation is the existing-test adjustment above.

## Fix report, round 1 (controller ruling: allowlist)

Changes:
- `check_tessera_folder` is now an allowlist. Root may hold only agent.yaml, installables.yaml, policy.yaml, .env, README.md, audit.log (files) and identity/, data/, tessera/, memory/, training/, knowledge/, work/ (dirs). Any other root entry is reported. `.gitkeep` is allowed anywhere.
- knowledge/ and work/: any file other than `.gitkeep` is reported.
- memory/: only `.gitkeep` and `peer__*` folders. `memory/private/` is reported as holding conversations; other folders are reported by name.
- training/: only `.gitkeep` and `training/adapters/<model>/<compartment>/`. Other files and folders are reported, e.g. `training/demo/checkpoint.bin is not an exported adapter`; a non-compartment adapter (`private`, `private.tmp`, `acme`) is reported; a file directly in `adapters/<model>/` is reported.
- data/: only `.gitkeep` and `data/tessera/`. Any other entry is reported, e.g. `data/calendar/ is not allowed`.
- Compartment, tools and other-connection checks are kept as before.
- `__main__.py`: `serve` on a tessera-facing agent refuses (stderr, return 2) unless its connections are exactly {"tessera"}. The check comes after the chat refusal and before the model loads.

Tests (`tests/test_tessera_folder.py`):
- `folder()` now builds the clean fixture the controller listed: .gitkeep files, README.md, identity/, data/tessera/, tessera/peer-1/s-1.jsonl, memory/peer__X/2026.jsonl, and the demo adapter. It returns no problems.
- Dirty cases added, each reported: `knowledge/demo/.me.md`, `memory/private/2026.jsonl`, `memory/demo/x.jsonl`, `training/demo/checkpoint.bin`, `training/adapters/org--model/notes.txt`, `training/adapters/org--model/private.tmp/`, `data/calendar/calendar.db`, root `notes.txt`.
- New test: `serve` on a one-compartment agent with a dummy connection returns 2 and names tessera.

RED: `.venv/Scripts/python.exe -m pytest -q tests/test_tessera_folder.py` gave `9 failed, 12 passed`. The 8 new dirty cases went unreported, and the serve test reached model loading (`OSError: org/model is not a local folder` from transformers).

GREEN:
- `.venv/Scripts/python.exe -m pytest -q tests/test_tessera_folder.py tests/test_config.py` gave `45 passed`.
- An intermediate run had 7 failures from a bug in my training-path message code (a relative path passed to `_rel` a second time). Fixed by keying messages off the root-relative path.
- Full suite `.venv/Scripts/python.exe -m pytest -q` gave `355 passed in 30.98s`.

Concerns: none new. The allowlist keeps the earlier message fragments ("private adapter", "acme", "training/demo", "tools", "exactly one", "knowledge/", "work/") so the earlier dirty cases still pass.
