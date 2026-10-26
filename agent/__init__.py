"""agent
=====
The user-facing half of the project: a CLI, a planner and an LLM wrapper.

The server (``mcp_server``) owns the tools and the policy. This package owns the
conversation: it discovers tools at run time, builds a prompt from their live
schemas, drives a bounded planning loop, and asks the user before anything
destructive happens.
"""

__version__ = "1.0.0"
