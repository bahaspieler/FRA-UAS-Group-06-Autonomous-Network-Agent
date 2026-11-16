# Testing

## Automated Tests

Run the dependency-free test suite with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The tests verify:

- A stopped UPF is detected, restarted, and verified.
- A rejected restart remains rejected and is not reported as recovery.
- The model-driven Responses API loop executes a requested local tool and returns its result.
- All model-facing tool schemas are strict.
- Unknown tools and non-allowlisted components are rejected.

## Real-Network Acceptance Test

Prerequisites:

1. Docker daemon is running on the supported Linux/VM environment.
2. The speed-test deployment is healthy.
3. The subscriber required by PacketRusher exists in MongoDB.
4. The UE has established a PDU session.

Procedure:

1. Record the initial `get_network_status` and `get_ue_status` results.
2. Use `/fault upf` and confirm the controlled failure.
3. Submit the recovery intent.
4. Approve only the proposed UPF restart.
5. Verify all services return to `running`.
6. Verify UE registration and PDU-session evidence in PacketRusher logs.
7. Run the bounded throughput tool.
8. Preserve the JSONL audit file and terminal recording in `results/`.

## Known Environment Limitation

Docker was not running during the initial implementation verification. The deterministic backend and all automated control-flow tests can still run without Docker. The Docker acceptance procedure must be executed on the course's Ubuntu/VM host before the professor demonstration.
