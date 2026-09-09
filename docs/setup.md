# Setup

## Prerequisites

- Python 3.11+ (developed and tested against 3.12)
- Git

## Install

```
git clone https://github.com/SriGoga/agent.git
cd agent
python -m venv .venv
```

Windows:
```
.venv\Scripts\activate
```
macOS/Linux:
```
source .venv/bin/activate
```

```
pip install -e ".[dev]"
```

## Run the test suite

```
pytest
```

Expect all tests to pass (54 as of Phase 7; see `README.md`'s Phase Log for the current
count and what each phase added).

## Run the URL Shortener service

```
python -m uvicorn url_shortener.main:app --reload
```

The service listens on `http://127.0.0.1:8000` by default. Try it:

```
curl -X POST http://127.0.0.1:8000/links \
  -H "Content-Type: application/json" \
  -d "{\"target_url\": \"https://example.com\", \"owner_id\": \"me\"}"
```

Then follow the returned `code` (`curl -i http://127.0.0.1:8000/<code>`) and check
`http://127.0.0.1:8000/links/<code>/analytics?owner_id=me`. Full endpoint reference:
`docs/api.md`.

By default the service uses a local file `url_shortener.db` (gitignored) in the working
directory. Override with the `URL_SHORTENER_IP_SALT` env var for the visitor-hashing salt
(see `docs/risks.md`) and `URL_SHORTENER_DB_PATH` for the database location.

## Run the orchestrator

The three scenario graphs from `src/scenarios/` can each be run against the real codebase:

```
python -m orchestrator.cli run --graph src/scenarios/greenfield.json --run-id gf1
python -m orchestrator.cli approve --run-id gf1 --node design-schema --approver <you> --reason "..."
python -m orchestrator.cli approve --run-id gf1 --node release-gate --approver <you> --reason "..."
python -m orchestrator.cli report --run-id gf1
```

Swap `greenfield.json` for `brownfield.json` or `ambiguous.json` to run those scenarios
(check each graph's JSON for which nodes have `"requires_approval": true` -- those are the
ones `approve` needs to unblock). Or run the self-contained engine walkthrough that needs no
approval-node lookups beyond what's printed:

```
python -m orchestrator.cli run --graph src/scenarios/demo.json
```

`run` prints the run id and every node's state after each call; `status --run-id <id>` and
`report --run-id <id>` can be called any time afterward. Run state lives under
`.orchestrator/runs/<run_id>/` (gitignored) -- delete that directory to reset.

## Troubleshooting

- **`ModuleNotFoundError: orchestrator` / `url_shortener` / `scenarios`**: the editable
  install (`pip install -e ".[dev]"`) didn't take, or you're not in the activated venv.
  Re-run the install step.
- **Port 8000 already in use**: pass `--port <n>` to the `uvicorn` command above.
- **A run is stuck at `paused_for_approval`**: check `status --run-id <id>` for which node is
  `needs_approval`, then `approve` (or `approve --reject`) it.
