"""Owner transport: chat from the terminal."""
from localagent.protocol.guard import AuthError

NEW_SESSION = "(new session with {name}: it doesn't remember the earlier conversation)"


def run_terminal(protocol, agent, secret: str, ask=None) -> int:
    try:
        session = protocol.open_owner_session(secret)
    except AuthError as e:
        print(f"Error: {e}")
        return 2
    print("Agent ready. Type 'exit' or Ctrl+C to quit. Type 'reset' to clear the conversation."
          + (" Type '/ask <name> <question>' to ask a connected agent, or '/talk <name>' to talk with it." if ask
             else "") + "\n")
    talking, last_session = None, None  # /talk: the connected agent every message goes to, and its session
    try:
        while True:
            try:
                text = input(f"You -> {talking}: " if talking else "You: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye.")
                return 0
            if not text:
                continue
            # While talking, only the bare word is a command: "Exit strategy?" or "Back up?" go to the other agent.
            if _is_bare(text, "exit") if talking else _is_command(text, "exit"):
                print("Goodbye.")
                return 0
            if talking:
                if _is_bare(text, "back"):
                    print("Back to your agent.\n")
                    talking = None
                    continue
                try:
                    print(ask(talking, text), "\n")
                except KeyboardInterrupt:  # a slow model can take a while to answer
                    print("\nGoodbye.")
                    return 0
                current = _session(ask, talking)
                if current and last_session and current != last_session:
                    print(NEW_SESSION.format(name=talking), "\n")
                last_session = current or last_session
                continue
            if _is_command(text, "reset"):
                session.reset_history()
                print("Conversation cleared (it stays saved in memory/).\n")
                continue
            word = text.split(maxsplit=1)[0].lower()
            if ask and word == "/ask":
                parts = text.split(maxsplit=2)
                print(ask(parts[1], parts[2]) if len(parts) == 3 else "Usage: /ask <name> <question>", "\n")
                continue
            if ask and word == "/talk":
                parts = text.split()
                problem = "Usage: /talk <name>" if len(parts) != 2 else getattr(ask, "check", lambda n: "")(parts[1])
                if problem:
                    print(problem, "\n")
                    continue
                talking, last_session = parts[1], _session(ask, parts[1])
                print(f"Talking with {talking}. Everything you type goes to it; '/back' returns to your agent.\n")
                continue
            print("Agent: ", end="", flush=True)
            try:
                for chunk in agent.respond_stream(session, text):
                    print(chunk, end="", flush=True)
            except Exception as e:
                print(f"\n[error] {e}")
            print("\n")
    finally:
        session.close()
        close_asks = getattr(ask, "close_all", None)
        if close_asks:
            close_asks()


def _session(ask, name: str):
    session_of = getattr(ask, "session", None)
    return session_of(name) if session_of else None


def _is_bare(text: str, command: str) -> bool:
    """`back`, `/back` or `Back.`, nothing more."""
    return text.lower().strip(" .!").lstrip("/") == command


def _is_command(text: str, command: str) -> bool:
    """`reset`, `/reset`, `Reset.` or `reset once` all count; a longer sentence is a normal message."""
    words = text.lower().strip(" .!").split()
    return bool(words) and words[0].lstrip("/") == command and len(words) <= 2
