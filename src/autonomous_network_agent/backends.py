import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence


class BackendError(RuntimeError):
    pass


class NetworkBackend:
    components: Sequence[str]

    def get_network_status(self) -> Dict[str, Any]:
        raise NotImplementedError

    def get_component_logs(self, component: str, tail: int) -> Dict[str, Any]:
        raise NotImplementedError

    def get_ue_status(self) -> Dict[str, Any]:
        raise NotImplementedError

    def restart_component(self, component: str) -> Dict[str, Any]:
        raise NotImplementedError

    def run_throughput_test(self, duration_seconds: int) -> Dict[str, Any]:
        raise NotImplementedError

    def inject_failure(self, component: str) -> Dict[str, Any]:
        raise NotImplementedError


class DemoNetworkBackend(NetworkBackend):
    """Deterministic in-memory network used for rehearsals and automated tests."""

    components = (
        "db",
        "nrf",
        "ausf",
        "udm",
        "udr",
        "nssf",
        "bsf",
        "pcf",
        "amf",
        "smf",
        "upf",
        "packetrusher",
        "iperf",
        "webui",
    )

    def __init__(self) -> None:
        self.states = {component: "running" for component in self.components}
        self.restart_counts = {component: 0 for component in self.components}

    def _check_component(self, component: str) -> None:
        if component not in self.components:
            raise BackendError("Component is not in the allowlist: " + component)

    def get_network_status(self) -> Dict[str, Any]:
        unhealthy = [name for name, state in self.states.items() if state != "running"]
        return {
            "backend": "demo",
            "healthy": not unhealthy,
            "components": dict(self.states),
            "unhealthy_components": unhealthy,
        }

    def get_component_logs(self, component: str, tail: int) -> Dict[str, Any]:
        self._check_component(component)
        if self.states[component] != "running":
            log = "%s: container stopped; service unavailable" % component
        elif component == "packetrusher" and self.states["upf"] != "running":
            log = "PDU session failed: UPF unavailable; N4 association is not established"
        else:
            log = "%s: service ready; heartbeat successful" % component
        return {"component": component, "tail": tail, "logs": log}

    def get_ue_status(self) -> Dict[str, Any]:
        core_ready = all(self.states[name] == "running" for name in ("amf", "smf", "upf"))
        return {
            "registered": core_ready,
            "pdu_session_established": core_ready,
            "ue_ip": "10.45.0.2" if core_ready else None,
            "evidence": (
                "Registration Accept and PDU Session Establishment Accept observed"
                if core_ready
                else "UE cannot establish a PDU session because a required core component is unavailable"
            ),
        }

    def restart_component(self, component: str) -> Dict[str, Any]:
        self._check_component(component)
        previous = self.states[component]
        self.states[component] = "running"
        self.restart_counts[component] += 1
        return {
            "component": component,
            "previous_state": previous,
            "state": "running",
            "restart_count": self.restart_counts[component],
        }

    def run_throughput_test(self, duration_seconds: int) -> Dict[str, Any]:
        ue = self.get_ue_status()
        if not ue["pdu_session_established"]:
            return {
                "success": False,
                "duration_seconds": duration_seconds,
                "error": "No active PDU session",
            }
        return {
            "success": True,
            "duration_seconds": duration_seconds,
            "throughput_mbps": 432.5,
            "retransmits": 0,
        }

    def inject_failure(self, component: str) -> Dict[str, Any]:
        self._check_component(component)
        self.states[component] = "stopped"
        return {"component": component, "state": "stopped", "injected": True}


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )


class DockerNetworkBackend(NetworkBackend):
    """Narrow Docker Compose adapter for the repository's speed-test scenario."""

    components = DemoNetworkBackend.components

    def __init__(self, project_root: Path, runner: CommandRunner = _default_runner) -> None:
        self.project_root = project_root.resolve()
        self.runner = runner
        self.compose_file = self.project_root / "compose-files/speed-test/docker-compose.yaml"
        self.env_file = self.project_root / "build-files/open5gs.env"

    def _check_component(self, component: str) -> None:
        if component not in self.components:
            raise BackendError("Component is not in the allowlist: " + component)

    def _run(self, command: Sequence[str]) -> str:
        try:
            completed = self.runner(command)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendError("Command failed: %s" % exc) from exc
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "unknown error").strip()
            raise BackendError(message)
        return completed.stdout

    def _compose(self, *arguments: str) -> List[str]:
        return [
            "docker",
            "compose",
            "-f",
            str(self.compose_file),
            "--env-file",
            str(self.env_file),
        ] + list(arguments)

    @staticmethod
    def _parse_compose_json(output: str) -> List[Dict[str, Any]]:
        output = output.strip()
        if not output:
            return []
        try:
            parsed = json.loads(output)
            return parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            rows = []
            for line in output.splitlines():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise BackendError("Unexpected docker compose JSON output") from exc
            return rows

    def get_network_status(self) -> Dict[str, Any]:
        rows = self._parse_compose_json(
            self._run(self._compose("ps", "--all", "--format", "json"))
        )
        states = {component: "missing" for component in self.components}
        health: Dict[str, str] = {}
        for row in rows:
            service = str(row.get("Service") or row.get("Name") or "")
            if service in states:
                states[service] = str(row.get("State") or "unknown").lower()
                if row.get("Health"):
                    health[service] = str(row["Health"]).lower()
        unhealthy = [
            name
            for name, state in states.items()
            if state not in ("running", "healthy") or health.get(name) == "unhealthy"
        ]
        return {
            "backend": "docker",
            "healthy": not unhealthy,
            "components": states,
            "health": health,
            "unhealthy_components": unhealthy,
        }

    def get_component_logs(self, component: str, tail: int) -> Dict[str, Any]:
        self._check_component(component)
        output = self._run(
            self._compose("logs", "--no-color", "--tail", str(tail), component)
        )
        return {"component": component, "tail": tail, "logs": output[-12000:]}

    def get_ue_status(self) -> Dict[str, Any]:
        output = self._run(
            self._compose("logs", "--no-color", "--tail", "300", "packetrusher")
        )
        registered = bool(re.search(r"Registration (?:Accept|complete|successful)", output, re.I))
        pdu = bool(re.search(r"PDU Session Establishment Accept", output, re.I))
        address = re.search(r"PDU address received:\s*([0-9.]+)", output, re.I)
        return {
            "registered": registered,
            "pdu_session_established": pdu,
            "ue_ip": address.group(1) if address else None,
            "evidence": "Parsed the latest 300 PacketRusher log lines",
        }

    def restart_component(self, component: str) -> Dict[str, Any]:
        self._check_component(component)
        self._run(self._compose("restart", component))
        return {"component": component, "state": "restart_requested"}

    def _container_ip(self, container: str) -> str:
        output = self._run(
            [
                "docker",
                "inspect",
                "--format",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                container,
            ]
        ).strip()
        if not re.fullmatch(r"[0-9.]+", output):
            raise BackendError("Could not determine container IP for " + container)
        return output

    def run_throughput_test(self, duration_seconds: int) -> Dict[str, Any]:
        logs = self.get_component_logs("packetrusher", 300)["logs"]
        vrf_match = re.search(r"VRF\s+(vrf[0-9]+)", logs, re.I)
        if not vrf_match:
            raise BackendError("No PacketRusher UE VRF found; verify the PDU session first")
        target = self._container_ip("iperf")
        output = self._run(
            [
                "docker",
                "exec",
                "packetrusher",
                "ip",
                "vrf",
                "exec",
                vrf_match.group(1),
                "iperf3",
                "-c",
                target,
                "-t",
                str(duration_seconds),
                "-J",
            ]
        )
        data = json.loads(output)
        summary = data.get("end", {}).get("sum_received", {})
        return {
            "success": "error" not in data,
            "duration_seconds": duration_seconds,
            "throughput_mbps": round(float(summary.get("bits_per_second", 0)) / 1_000_000, 2),
            "raw_error": data.get("error"),
        }

    def inject_failure(self, component: str) -> Dict[str, Any]:
        self._check_component(component)
        self._run(self._compose("stop", component))
        return {"component": component, "state": "stopped", "injected": True}
