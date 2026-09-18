# perplexity-agent

Web-grounded answers via the [Perplexity Agent API](https://docs.perplexity.ai/docs/agent-api/quickstart)
(`POST https://api.perplexity.ai/v1/agent`), using the official `perplexityai` SDK.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Create an API key in the [API Console](https://console.perplexity.ai) and export it in your
own shell (never paste it into chat, commit it, or log it):

```bash
export PERPLEXITY_API_KEY=...
```

## Usage

```python
from perplexity_agent import ask

answer = ask("What's the latest stable release of Python?")
print(answer.text)          # answer.text is response.output_text
for c in answer.citations:  # sources pulled from annotations + search_results
    print(c.url, c.title)
```

`ask()` takes either `preset` (default `"low"`; presets bundle a model, tools, and token
limits -- see [presets](https://docs.perplexity.ai/docs/agent-api/presets)) or `model` to
pick a specific frontier model directly, plus `tools`, `instructions`,
`previous_response_id` (multi-turn), and `response_format` (structured JSON-schema output).
Passing `model` without `tools` enables `web_search` automatically so the call stays
grounded.

CLI:

```bash
python -m perplexity_agent "What's the latest stable release of Python?" --show-citations
```

## Error handling

`ask()` raises:
- `MissingAPIKeyError` if `PERPLEXITY_API_KEY` isn't set.
- `AgentAuthenticationError` on a 401 (invalid/expired key -- rotate it in the console if it
  was ever exposed).
- `AgentRateLimitError` on a 429, with `.retry_after` set from the `Retry-After` header when
  present; honor it before retrying.

## Development

```bash
pip install -e ".[dev]"
ruff check .
mypy src
pytest
```

`scripts/smoke_test.py` makes one real, minimal request and prints only the response status
and shape (never the key or the API response's raw content):

```bash
python scripts/smoke_test.py
```
