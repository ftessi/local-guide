from pathlib import Path
from dotenv import load_dotenv

# Load .env before importing transformers so HF_HOME points at W:\LocalAgent\models
load_dotenv()

from agent.llm import LLMEngine
from agent.session import SessionContext
from agent.core import Agent
from agent.config import MODEL_ID, USE_4BIT

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


def main():
    print(f"Loading model {MODEL_ID}...")
    llm = LLMEngine(model_id=MODEL_ID, use_4bit=USE_4BIT)
    session = SessionContext(knowledge_dir=KNOWLEDGE_DIR)
    agent = Agent(llm=llm, session=session)
    print("Agent ready. Type 'exit' or Ctrl+C to quit. Type 'reset' to clear history.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() == "exit":
            print("Goodbye.")
            break
        if user_input.lower() == "reset":
            agent.reset()
            print("Conversation history cleared.\n")
            continue

        print("Agent: ", end="", flush=True)
        for chunk in agent.chat_stream(user_input):
            print(chunk, end="", flush=True)
        print("\n")


if __name__ == "__main__":
    main()
