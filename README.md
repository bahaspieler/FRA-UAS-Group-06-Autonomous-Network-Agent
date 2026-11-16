# Autonomous Network Agent for Open5GS

Group 06 project for the Mobile Computing module at Frankfurt University of Applied Sciences, winter semester 2026/27.

Our project explores a small but practical question: how can an agent help operate a 5G test network without being given unrestricted access to the host system? The result is a terminal-based agent that can inspect an Open5GS deployment, diagnose a limited set of failures, request approval for a corrective action, and check whether the network recovered.

The repository is based on the Open5GS course template. We kept the supplied deployment scenarios and added the agent implementation, tests, and project documentation.

## What the MVP can do

The agent has five operations:

- inspect the state of the network functions;
- check UE registration and PDU-session state;
- read a bounded number of log lines from an allowlisted component;
- restart an allowlisted component after operator approval; and
- run a bounded throughput test.

It does not receive a general-purpose shell. Every tool request and result is written to an audit log, and a repair is only reported as successful after the network and UE state have been checked again.

Two modes are available. The deterministic mode makes the demonstration reproducible without an API key or a running Docker environment. The optional model-driven mode uses the same guarded tools and approval checks.

## Quick start

Python 3.9 or newer is required. The offline demonstration has no third-party Python dependencies.

Run a complete fault-and-recovery scenario:

```bash
PYTHONPATH=src python3 -m autonomous_network_agent \
  --backend demo \
  --inject-fault upf \
  --once "Check the network, repair safe failures, and verify the result" \
  --yes
```

The `--yes` option is useful for a repeatable demonstration because it approves the controlled fault and the proposed restart automatically. Leave it out to answer each approval prompt yourself.

For an interactive session, run:

```bash
PYTHONPATH=src python3 -m autonomous_network_agent --backend demo
```

Inside the session, `/tools` lists the available operations and `/fault upf` creates a controlled failure.

## Running against Open5GS

The Docker backend currently uses the supplied speed-test deployment:

```bash
docker compose \
  -f compose-files/speed-test/docker-compose.yaml \
  --env-file=build-files/open5gs.env \
  up -d
```

After the deployment is running and its subscriber is configured, start the agent with:

```bash
PYTHONPATH=src python3 -m autonomous_network_agent --backend docker
```

The course [Handbook](Handbook.md), [deployment overview](docs/deployments.md), and [Compose guide](docs/compose.md) contain the complete environment setup and configuration notes.

## Optional model-driven mode

To use a model for the tool-selection loop, provide an API key and a model available to your account:

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="..."
PYTHONPATH=src python3 -m autonomous_network_agent \
  --backend demo \
  --brain openai
```

The application remains responsible for validating arguments and requesting approval. Switching the reasoning mode does not give the model additional permissions.

## Tests

Run the test suite from the repository root:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The tests cover recovery and rejection paths, tool allowlists, strict schemas, and the model-driven tool loop.

## Repository layout

```text
src/autonomous_network_agent/   Agent, backends, tools, and audit logging
tests/                          Automated tests
compose-files/                  Open5GS deployment scenarios from the template
configs/                        Open5GS, UERANSIM, and PacketRusher configuration
build-files/                    Container build files and environment defaults
docs/                           Project and template documentation
```

Project-specific documentation:

- [Architecture](docs/architecture.md)
- [Implementation](docs/implementation.md)
- [Testing and acceptance procedure](docs/testing.md)

Audit records are created under `results/agent-runs/`. They are local run artifacts and are excluded from version control.
