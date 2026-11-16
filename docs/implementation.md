# Implementation

## Package Layout

```text
src/autonomous_network_agent/
├── agent.py       # deterministic and model-driven tool loops
├── audit.py       # append-only JSONL evidence
├── backends.py    # demo and Docker Compose adapters
├── cli.py         # terminal chat and one-shot interface
└── tools.py       # strict schemas, policy, approval, dispatch
```

## Running the Reproducible Demo

```bash
PYTHONPATH=src python3 -m autonomous_network_agent \
  --backend demo \
  --inject-fault upf \
  --once "Operate the network, diagnose failures, repair them safely, and verify recovery" \
  --yes
```

Remove `--yes` to show the human approval prompt.

## Running Against Docker

First start and prepare the repository's speed-test deployment as described in `docs/deployments.md`. Then run:

```bash
PYTHONPATH=src python3 -m autonomous_network_agent --backend docker
```

Useful terminal commands:

```text
/tools
/fault upf
Ensure every UE is registered and repair safe failures.
Run a throughput test.
/quit
```

The Docker backend invokes Docker with argument arrays and never uses a shell. The current MVP is deliberately bound to `compose-files/speed-test/docker-compose.yaml`.

## Running With a Live Model

Set an API key and choose a model available to the account:

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="..."
PYTHONPATH=src python3 -m autonomous_network_agent \
  --backend demo \
  --brain openai
```

The live adapter sends the five strict function schemas to the Responses API. Function requests are dispatched locally; tool results are sent back to the model until it returns a final answer. The application, not the model, owns approval enforcement.

## Audit Evidence

Each run creates `results/agent-runs/<session-id>.jsonl`. Records include the user request, tool requests, approvals, tool results, and final report. API keys are never written to the log.
