"""Command-line entry point: python -m perplexity_agent "question"."""

from __future__ import annotations

import argparse
import sys

from .client import AgentAPIError, MissingAPIKeyError, ask


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ask a web-grounded question via the Perplexity Agent API."
    )
    parser.add_argument("query", help="The question to ask.")
    parser.add_argument("--preset", default="low", help="Agent preset to use (default: low).")
    parser.add_argument("--model", default=None, help="Explicit model instead of a preset.")
    parser.add_argument(
        "--show-citations", action="store_true", help="Print source citations after the answer."
    )
    args = parser.parse_args(argv)

    try:
        answer = ask(args.query, preset=args.preset, model=args.model)
    except (MissingAPIKeyError, AgentAPIError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(answer.text)
    if args.show_citations and answer.citations:
        print("\nSources:")
        for citation in answer.citations:
            label = citation.title or citation.url
            print(f"- {label} ({citation.url})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
