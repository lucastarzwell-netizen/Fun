#!/usr/bin/env python3
"""Minimal real request against the Perplexity Agent API.

Prints only the response status and shape -- never the API key or full
answer text. Usage:

    export PERPLEXITY_API_KEY=...   # in your own shell, never in chat
    python scripts/smoke_test.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from perplexity_agent import AgentAPIError, ask  # noqa: E402
from perplexity_agent.client import AgentAuthenticationError, AgentRateLimitError  # noqa: E402


def main() -> int:
    if not os.environ.get("PERPLEXITY_API_KEY"):
        print(
            "PERPLEXITY_API_KEY is not set. Create a key at https://console.perplexity.ai "
            "and export it in your own shell before running this smoke test.",
            file=sys.stderr,
        )
        return 1

    try:
        answer = ask("What is the current stable version of Python?", preset="low")
    except AgentAuthenticationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except AgentRateLimitError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except AgentAPIError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print("status=200 (request succeeded)")
    print(f"response.id: {'present' if answer.id else 'missing'}")
    print(f"response.status: {answer.status}")
    text_state = "non-empty" if answer.text.strip() else "empty"
    print(f"output_text: {text_state} ({len(answer.text)} chars)")
    print(f"citations: {len(answer.citations)} source(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
