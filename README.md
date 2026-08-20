# Simple Tool-Use Agent

A minimal, extensible agent built directly on the Anthropic Messages API
(no framework). It runs an agentic loop: send a message, execute any tools
Claude asks for, feed the results back, repeat until Claude produces a
final answer.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then edit .env and add your ANTHROPIC_API_KEY
export $(grep -v '^#' .env | xargs)   # or use a tool like python-dotenv/direnv
```

## Run (CLI)

```bash
python agent.py
```

## Run (web chat)

```bash
python server.py
```

Then open http://localhost:5000 in a browser for a chat UI. Each browser
tab gets its own conversation (tracked via a session id in localStorage);
conversations live in memory only and reset when the server restarts.

## Project layout

- `agent.py` — the agentic loop (`Agent.send`) and a simple CLI chat loop.
- `server.py` — Flask web server exposing the same agent over `/api/chat`.
- `static/index.html` — the browser chat UI served by `server.py`.
- `tools.py` — tool schemas (`TOOLS`) and their implementations
  (`TOOL_FUNCTIONS`). Included out of the box: `calculator`,
  `get_current_time`, `read_file`, `write_file`, `list_files` (file tools
  are sandboxed to `./sandbox/`).

## Adding a new tool

1. Write a plain Python function in `tools.py`.
2. Add a matching JSON-schema entry to `TOOLS` (name, description, input
   schema).
3. Register the function in `TOOL_FUNCTIONS` under the same name.

Nothing in `agent.py` needs to change — it reads both lists dynamically.

## Notes

- `MAX_TOOL_ITERATIONS` in `agent.py` caps how many tool round-trips a
  single turn can take, to avoid infinite loops.
- The file tools are restricted to a `sandbox/` directory so the agent
  can't read or write arbitrary paths on the host.
