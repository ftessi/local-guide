# Git Guide — What to Commit and What Not

Remote: `git@github.com:ftessi/local-guide.git` · branch `master`

The `.gitignore` in the repo root already enforces everything below. This guide explains *why*,
so you can decide for new files.

---

## ✅ Commit

| Path | Why |
|---|---|
| `agent/`, `main.py`, `server.py` | The code |
| `static/` | Phone web app (HTML, service worker, manifest, icon) |
| `tests/`, `pytest.ini` | Test suite |
| `scripts/` | Helper scripts (`start_server.bat`, GPU diagnostics, smoke test) |
| `knowledge/public/` | General behaviour instructions — nothing personal |
| `docs/` | All documentation |
| `requirements.txt` | So the env can be rebuilt |
| `.env.example` | Template showing which settings exist — **no real values** |
| `.gitignore` | |

## ❌ Never commit

| Path | Why | How to recreate on a new machine |
|---|---|---|
| `.env` | Contains `AGENT_SECRET` and the VAPID private key — anyone with these can talk to your agent and send push notifications | Copy `.env.example` → `.env`, generate a new secret |
| `*.pem` (`.vapid_private.pem`) | VAPID private key | Regenerate (see plan Task 8); phones re-subscribe automatically |
| `push_subscriptions.json` | Your phones' push endpoints | Recreated when the phone app connects |
| `knowledge/private/` | Personal facts about you | Copy manually / keep a private backup |
| `calendar.db` | Your reminders (personal data) | Created automatically on first run |
| `models/` | ~6GB of HuggingFace weights; GitHub rejects files >100MB anyway | Downloaded automatically on first run |
| `.venv/` | Machine-specific, ~GBs | `python -m venv .venv` + `pip install -r requirements.txt` |
| `__pycache__/`, `.pytest_cache/` | Generated | — |
| `.claude/settings.local.json` | Your local Claude Code permissions | — |

> If the repo is **public**, double-check `docs/` before pushing — never paste the real
> `AGENT_SECRET`, domain-specific tunnel IDs or credential file contents into a doc.

---

## Committing

```powershell
cd W:\LocalAgent
git status                 # review: nothing from the ❌ list should appear
git add -A                 # .gitignore filters out the secrets
git status                 # review AGAIN what is staged
git commit -m "Add agent, server, calendar, push, docs"
git push origin master
```

Safety check before every push — this must print nothing:
```powershell
git ls-files | Select-String -Pattern "\.env$|\.pem$|calendar\.db|push_subscriptions|knowledge/private|models/"
```

---

## If a secret was committed by accident

1. **Rotate it first** — a pushed secret is compromised even if you delete it later:
   new `AGENT_SECRET` in `.env`; new VAPID keys if the `.pem`/private key leaked.
2. Remove it from tracking: `git rm --cached .env` and commit.
3. If it was already pushed, rewriting history (`git filter-repo`) only helps if nobody cloned it —
   rotation in step 1 is what actually protects you.

---

## Setting up on another machine (e.g. the MacBook)

```bash
git clone git@github.com:ftessi/local-guide.git LocalAgent
cd LocalAgent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt                     # Mac: see docs/Setup/macbook-m4.md (no CUDA)
cp .env.example .env                                # then fill in values
mkdir -p knowledge/private                          # add your private notes
```
