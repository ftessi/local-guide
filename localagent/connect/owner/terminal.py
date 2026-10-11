"""Owner transport: chat from the terminal."""
from localagent.protocol.guard import AuthError


def run_terminal(protocol, agent, secret: str) -> int:
    try:
        session = protocol.open_owner_session(secret)
    except AuthError as e:
        print(f"Error: {e}")
        return 2
    print("Agent ready. Type 'exit' or Ctrl+C to quit. Type 'reset' to clear the conversation.\n")
    try:
        while True:
            try:
                text = input("You: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye.")
                return 0
            if not text:
                continue
            if text.lower() == "exit":
                print("Goodbye.")
                return 0
            if text.lower() == "reset":
                session.reset_history()
                print("Conversation cleared (it stays saved in memory/).\n")
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
