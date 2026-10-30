# test_connector.py
import sys
# pyrefly: ignore [missing-import]
from response_generation.llm_engine import LLMConnector

def test_engine_link():
    print("🚀 Running isolated validation check for local Ollama/Gemma module...")
    connector = LLMConnector()
    
    # Mock data layout simulating what will arrive from your Intent Engine module
    mock_intent_command = {"intent": "COMMAND", "entities": {"app": "task_manager"}}
    mock_text_command = "Open the task manager to look for leaks"
    
    print(f"\n🔹 Simulating incoming intent rule text: '{mock_text_command}'")
    reply_command = connector.generate_response(mock_text_command, mock_intent_command)
    print(f"🤖 [Gemma Automation Response]:\n--> {reply_command}\n")

    mock_intent_chat = {"intent": "CHAT", "entities": {}}
    mock_text_chat = "Hello! Who are you?"
    
    print(f"🔹 Simulating incoming intent rule text: '{mock_text_chat}'")
    reply_chat = connector.generate_response(mock_text_chat, mock_intent_chat)
    print(f"🤖 [Gemma General Conversational Response]:\n--> {reply_chat}\n")

if __name__ == "__main__":
    test_engine_link()
