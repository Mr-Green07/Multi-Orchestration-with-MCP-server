"""
offline_agent.py
================
Command-line interface for the offline agent.

Usage
-----
    python offline_agent.py                      # interactive chat
    python offline_agent.py --show-tools         # print tool calls/results
    python offline_agent.py --db database/app.db # enable query_sqlite
    python offline_agent.py --index indexes/default   # load a document index
    python offline_agent.py --debug              # verbose logging to console
    python offline_agent.py --no-quant           # load without 4-bit (CPU/debug)

Interactive commands
---------------------
    /help            show help
    /exit, /quit     leave
    /clear           clear the conversation history
    /tools           list the available tools
    /show            toggle display of tool calls
    /debug           toggle debug logging
    /db <path>       select a SQLite database (relative to database/)
    /index <dir>     load a document index directory
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import security
import tools
from agent_controller import AgentController
from tools import ToolContext


BANNER = r"""
==============================================================
  Offline Llama 3.2 1B Agent  (4-bit QLoRA, fully local)
  Type your request, or /help for commands.  Ctrl-C to abort.
==============================================================
"""


def make_confirm():
    """Interactive y/N confirmation used before overwriting files."""
    def confirm(message: str) -> bool:
        try:
            reply = input(f"  [confirm] {message} [y/N]: ").strip().lower()
        except EOFError:
            return False
        return reply in {"y", "yes"}
    return confirm


def cmd_help():
    print(
        "Commands:\n"
        "  /help          show this help\n"
        "  /exit, /quit   leave the agent\n"
        "  /clear         clear conversation history\n"
        "  /tools         list available tools\n"
        "  /show          toggle showing tool calls/results\n"
        "  /debug         toggle debug logging to console\n"
        "  /db <path>     select a SQLite database (inside database/)\n"
        "  /index <dir>   load a document index directory\n"
    )


def load_index(ctx: ToolContext, index_dir: str, embed_model: str | None, logger):
    import retrieval
    try:
        retriever = retrieval.Retriever.load(index_dir, embed_model)
    except FileNotFoundError as exc:
        print(f"  ! {exc}")
        return
    except Exception as exc:
        print(f"  ! Failed to load index: {exc}")
        logger.error("INDEX_LOAD_ERROR: %s", exc)
        return
    ctx.retriever = retriever
    n = len(retriever.meta)
    print(f"  Loaded index '{index_dir}' ({n} chunks, model="
          f"{retriever.config.get('embed_model', '?')}).")


def select_db(ctx: ToolContext, db_arg: str):
    """Resolve a DB path; model-facing 'db' args are sandboxed to database/."""
    p = Path(db_arg)
    if p.is_absolute() or db_arg.startswith(("/", "\\")):
        print("  ! Use a path relative to the database/ directory.")
        return
    try:
        resolved = security.resolve_in_dir(db_arg, security.DATABASE_DIR)
    except security.SecurityError as exc:
        print(f"  ! {exc}")
        return
    if not resolved.exists():
        print(f"  ! Database not found: {db_arg}")
        return
    ctx.db_path = str(resolved)
    print(f"  Database selected: database/{resolved.name}")


def interactive_loop(agent: AgentController, ctx: ToolContext, args, logger):
    print(BANNER)
    while True:
        try:
            user_input = input("User: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return

        if not user_input:
            continue

        # --- slash commands ---
        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""
            if cmd in ("/exit", "/quit"):
                print("Goodbye.")
                return
            if cmd == "/help":
                cmd_help()
            elif cmd == "/clear":
                agent.clear()
                print("  Conversation history cleared.")
            elif cmd == "/tools":
                print(tools.describe_tools())
            elif cmd == "/show":
                agent.show_tools = not agent.show_tools
                print(f"  show-tools = {agent.show_tools}")
            elif cmd == "/debug":
                lvl = "DEBUG" if logger.level != 10 else "INFO"
                import logging
                logger.setLevel(logging.DEBUG if lvl == "DEBUG" else logging.INFO)
                print(f"  logging level = {lvl}")
            elif cmd == "/db":
                if arg:
                    select_db(ctx, arg)
                else:
                    print("  usage: /db <path-inside-database/>")
            elif cmd == "/index":
                if arg:
                    load_index(ctx, arg, args.embed_model, logger)
                else:
                    print("  usage: /index <index-dir>")
            else:
                print(f"  Unknown command: {cmd}. Type /help.")
            continue

        # --- normal request ---
        start = time.time()
        result = agent.run(user_input)
        elapsed = time.time() - start

        print(f"\nAgent: {result.answer}")
        meta = f"  ({result.steps} step(s), {elapsed:.2f}s"
        if result.exhausted:
            meta += ", step-limit reached"
        meta += ")"
        print(meta + "\n")


def build_real_agent(args, logger):
    """Load the local model and wire up a real generate function."""
    import model_loader
    print("Loading local model (this can take a moment)...")
    model, tokenizer = model_loader.load_model_and_tokenizer(
        model_dir=args.model_dir,
        adapter_dir=args.adapter_dir,
        use_quant=not args.no_quant,
    )
    generate_fn = model_loader.build_generate_fn(
        model, tokenizer, max_new_tokens=args.max_new_tokens,
    )
    mem = model_loader.report_memory()
    print(f"Model ready. Device: {mem.get('device')}", end="")
    if "allocated_mb" in mem:
        print(f" | GPU allocated: {mem['allocated_mb']} MB", end="")
    print()
    return generate_fn


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Fully offline Llama 3.2 1B agent.")
    p.add_argument("--model-dir", default=str(security.MODELS_DIR / "llama-3.2-1b-instruct"))
    p.add_argument("--adapter-dir", default=str(security.ADAPTERS_DIR / "llama-3.2-1b-qlora"))
    p.add_argument("--embed-model", default=None,
                   help="Local sentence-transformers dir/name for retrieval.")
    p.add_argument("--index", default=None, help="Index directory to load at startup.")
    p.add_argument("--db", default=None, help="SQLite DB path (inside database/) to enable at startup.")
    p.add_argument("--max-steps", type=int, default=security.MAX_STEPS)
    p.add_argument("--max-new-tokens", type=int, default=security.MAX_MODEL_NEW_TOKENS)
    p.add_argument("--no-quant", action="store_true", help="Disable 4-bit quantization.")
    p.add_argument("--debug", action="store_true", help="Verbose logging to the console.")
    p.add_argument("--show-tools", action="store_true", help="Print tool calls and results.")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logger = security.get_logger(debug=args.debug, to_console=args.debug)
    logger.info("CLI_START args=%s", vars(args))

    ctx = ToolContext(confirm=make_confirm(), logger=logger)

    # Optional startup wiring.
    if args.db:
        select_db(ctx, args.db)
    if args.index:
        load_index(ctx, args.index, args.embed_model, logger)

    try:
        generate_fn = build_real_agent(args, logger)
    except Exception as exc:
        print("\nERROR: could not load the local model.")
        print(f"  {exc}\n")
        print("Troubleshooting: ensure the base model is in "
              f"'{args.model_dir}', the adapter in '{args.adapter_dir}', that "
              "torch/transformers/peft/bitsandbytes are installed, and that a "
              "CUDA GPU is available (or use --no-quant). See README > Troubleshooting.")
        logger.error("MODEL_LOAD_FAILED: %s", exc)
        return 1

    agent = AgentController(
        generate_fn=generate_fn, ctx=ctx, logger=logger,
        max_steps=args.max_steps, show_tools=args.show_tools,
    )
    interactive_loop(agent, ctx, args, logger)
    return 0


if __name__ == "__main__":
    sys.exit(main())
