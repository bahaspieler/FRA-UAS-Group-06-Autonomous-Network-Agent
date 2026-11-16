import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .agent import AgentError, DeterministicAgent, OpenAIResponsesAgent
from .audit import AuditLogger
from .backends import DemoNetworkBackend, DockerNetworkBackend
from .tools import ToolRegistry


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _observer(event: str, data: Mapping[str, Any]) -> None:
    if event == "tool_requested":
        print("  -> tool: %s %s [%s]" % (data["tool"], json.dumps(data["arguments"]), data["risk"]))
    elif event == "tool_result":
        result = data["result"]
        marker = "ok" if result.get("ok") else "error"
        print("  <- tool: %s [%s]" % (data["tool"], marker))
    elif event == "tool_rejected":
        print("  xx tool rejected: %s" % data["tool"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autonomous 5G Network Agent MVP")
    parser.add_argument("--backend", choices=("demo", "docker"), default="demo")
    parser.add_argument("--brain", choices=("deterministic", "openai"), default="deterministic")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL"))
    parser.add_argument("--once", help="Run one request instead of opening interactive chat")
    parser.add_argument("--inject-fault", choices=DemoNetworkBackend.components)
    parser.add_argument("--yes", action="store_true", help="Approve state changes without prompting")
    parser.add_argument("--no-audit-file", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    root = _project_root()
    audit_dir = None if args.no_audit_file else root / "results/agent-runs"
    audit = AuditLogger(audit_dir)
    backend = DemoNetworkBackend() if args.backend == "demo" else DockerNetworkBackend(root)

    def approve(tool: str, arguments: Mapping[str, Any]) -> bool:
        if args.yes:
            return True
        answer = input("Approve %s %s? [y/N] " % (tool, json.dumps(dict(arguments)))).strip().lower()
        return answer in ("y", "yes")

    tools = ToolRegistry(backend, audit, approve, _observer)
    if args.brain == "openai":
        if not args.model:
            raise SystemExit("--model or OPENAI_MODEL is required for --brain openai")
        agent = OpenAIResponsesAgent(tools, audit, args.model)
    else:
        agent = DeterministicAgent(tools, audit)

    if args.inject_fault:
        if not args.yes:
            answer = input("Inject controlled failure by stopping %s? [y/N] " % args.inject_fault).strip().lower()
            if answer not in ("y", "yes"):
                print("Fault injection cancelled.")
            else:
                result = backend.inject_failure(args.inject_fault)
                audit.record("fault_injected", **result)
                print("Injected fault: " + json.dumps(result))
        else:
            result = backend.inject_failure(args.inject_fault)
            audit.record("fault_injected", **result)
            print("Injected fault: " + json.dumps(result))

    print("Autonomous Network Agent MVP")
    print("backend=%s brain=%s session=%s" % (args.backend, args.brain, audit.session_id))
    if audit.path:
        print("audit=%s" % audit.path)

    if args.once:
        try:
            print("\nagent> " + agent.run(args.once))
            return 0
        except (AgentError, KeyboardInterrupt) as exc:
            print("\nerror> %s" % exc)
            return 1

    print("Commands: /help, /tools, /fault COMPONENT, /quit")
    while True:
        try:
            prompt = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return 0
        if not prompt:
            continue
        if prompt in ("/quit", "/exit"):
            print("bye")
            return 0
        if prompt == "/help":
            print("Ask for network status, component logs, diagnosis/repair, or a throughput test.")
            continue
        if prompt == "/tools":
            print(json.dumps(tools.descriptions(), indent=2))
            continue
        if prompt.startswith("/fault "):
            component = prompt.split(maxsplit=1)[1].strip()
            if component not in backend.components:
                print("Unknown component. Allowed: " + ", ".join(backend.components))
                continue
            answer = "yes" if args.yes else input("Stop %s to create a controlled fault? [y/N] " % component)
            if answer.strip().lower() in ("y", "yes"):
                result = backend.inject_failure(component)
                audit.record("fault_injected", **result)
                print(json.dumps(result, indent=2))
            continue
        try:
            print("\nagent> " + agent.run(prompt))
        except AgentError as exc:
            print("\nerror> %s" % exc)


if __name__ == "__main__":
    raise SystemExit(main())
