# Architecture

## System Context

```text
Operator
   |
   | natural-language intent
   v
Terminal Chat
   |
   v
Agent Brain -----------------------------+
   |                                     |
   | strict function calls               | final explanation
   v                                     |
Guarded Tool Registry                    |
   |                                     |
   +-- read tools -----------------------+
   |
   +-- write tool -> approval gate
   |
   v
Network Backend
   +-- deterministic demo state
   +-- Docker Compose / Open5GS / PacketRusher
   |
   v
Audit JSONL
```

## Control Loop

```text
Intent -> Observe -> Diagnose -> Propose -> Approve -> Act -> Verify -> Report
             ^                                             |
             +---------------------------------------------+
```

The agent is not trusted to declare success from its own reasoning. Recovery is accepted only when new observations show both healthy components and a registered UE with an established PDU session.

## Safety Boundaries

- The model sees JSON-schema tools, not a shell.
- Component names are enumerated in the schema and checked by the backend.
- Log tail and throughput-test duration are bounded.
- State-changing calls require an application-side approval independent of the model.
- Every tool result is treated as evidence and retained in the audit log.
- Rejected or failed actions must lead to escalation rather than a success claim.

## Modes

| Dimension | Option | Purpose |
|---|---|---|
| Backend | `demo` | Deterministic rehearsal and automated testing |
| Backend | `docker` | Real Open5GS speed-test deployment |
| Brain | `deterministic` | Guaranteed classroom demo with predictable decisions |
| Brain | `openai` | Actual model-selected function calls through the Responses API |
