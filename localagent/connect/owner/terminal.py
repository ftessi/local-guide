"""Owner transport: chat from the terminal."""
from localagent.protocol.guard import AuthError


def run_terminal(protocol, agent, secret: str, ask=None) -> int:
    try:
        session = protocol.open_owner_session(secret)
    except AuthError as e:
        print(f"Error: {e}")
        return 2
    print("Agent ready. Type 'exit' or Ctrl+C to quit. Type 'reset' to clear the conversation."
          + (" Type '/ask <name> <question>' to ask a connected agent." if ask else "") + "\n")
    try:
        while True:
            try:
                text = input("You: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye.")
                return 0
            if not text:
                continue
            if _is_command(text, "exit"):
                print("Goodbye.")
                return 0
            if _is_command(text, "reset"):
                session.reset_history()
                print("Conversation cleared (it stays saved in memory/).\n")
                continue
            if ask and text.lower().startswith("/ask"):
                parts = text.split(maxsplit=2)
                print(ask(parts[1], parts[2]) if len(parts) == 3 else "Usage: /ask <name> <question>", "\n")
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


def _is_command(text: str, command: str) -> bool:
    """`reset`, `/reset`, `Reset.` or `reset once` all count; a longer sentence is a normal message."""
    words = text.lower().strip(" .!").split()
    return bool(words) and words[0].lstrip("/") == command and len(words) <= 2
