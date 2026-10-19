"""
Quick test: load the model ONCE via model_loader, then query interactively.
"""
from model_loader import load_model_and_tokenizer, build_generate_fn

# Load once — stays in memory
print("Loading model...")
model, tokenizer = load_model_and_tokenizer()
generate = build_generate_fn(model, tokenizer)
print("Model loaded!\n")

# Query loop — no reloading
while True:
    user_input = input("Write your query (or 'quit' to exit): ").strip()
    if user_input.lower() in ("quit", "exit", "q"):
        break

    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant that helps students gain knowledge and improved insights.",
        },
        {
            "role": "user",
            "content": user_input,
        },
    ]

    response = generate(messages)
    print(f"\n{response}\n")
