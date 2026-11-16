import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional

from .audit import AuditLogger
from .backends import NetworkBackend


class ToolError(RuntimeError):
    pass


ApprovalCallback = Callable[[str, Mapping[str, Any]], bool]
Observer = Callable[[str, Mapping[str, Any]], None]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    risk: str
    handler: Callable[..., Dict[str, Any]]

    def model_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "strict": True,
        }


class ToolRegistry:
    def __init__(
        self,
        backend: NetworkBackend,
        audit: AuditLogger,
        approval: ApprovalCallback,
        observer: Optional[Observer] = None,
    ) -> None:
        self.backend = backend
        self.audit = audit
        self.approval = approval
        self.observer = observer or (lambda _event, _data: None)
        component_schema = {"type": "string", "enum": list(backend.components)}
        self._tools: Dict[str, ToolSpec] = {}
        self._register(
            ToolSpec(
                "get_network_status",
                "Inspect all allowlisted services and report unhealthy or missing components.",
                {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                "read",
                backend.get_network_status,
            )
        )
        self._register(
            ToolSpec(
                "get_ue_status",
                "Check UE registration, PDU session establishment, and the assigned UE address.",
                {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                "read",
                backend.get_ue_status,
            )
        )
        self._register(
            ToolSpec(
                "get_component_logs",
                "Read recent logs for one allowlisted network component.",
                {
                    "type": "object",
                    "properties": {
                        "component": component_schema,
                        "tail": {"type": "integer", "minimum": 1, "maximum": 500},
                    },
                    "required": ["component", "tail"],
                    "additionalProperties": False,
                },
                "read",
                backend.get_component_logs,
            )
        )
        self._register(
            ToolSpec(
                "restart_component",
                "Restart one allowlisted service. This mutates network state and requires operator approval.",
                {
                    "type": "object",
                    "properties": {"component": component_schema},
                    "required": ["component"],
                    "additionalProperties": False,
                },
                "write",
                backend.restart_component,
            )
        )
        self._register(
            ToolSpec(
                "run_throughput_test",
                "Run a bounded iPerf test through the PacketRusher UE VRF and return measured throughput.",
                {
                    "type": "object",
                    "properties": {
                        "duration_seconds": {"type": "integer", "minimum": 1, "maximum": 10}
                    },
                    "required": ["duration_seconds"],
                    "additionalProperties": False,
                },
                "test",
                backend.run_throughput_test,
            )
        )

    def _register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    @property
    def names(self) -> List[str]:
        return list(self._tools)

    def model_schemas(self) -> List[Dict[str, Any]]:
        return [spec.model_schema() for spec in self._tools.values()]

    def descriptions(self) -> List[Dict[str, str]]:
        return [
            {"name": spec.name, "risk": spec.risk, "description": spec.description}
            for spec in self._tools.values()
        ]

    @staticmethod
    def _validate_arguments(spec: ToolSpec, arguments: Mapping[str, Any]) -> Optional[str]:
        schema = spec.parameters
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            return "Unexpected arguments: " + ", ".join(unknown)
        missing = [name for name in required if name not in arguments]
        if missing:
            return "Missing required arguments: " + ", ".join(missing)
        for name, value in arguments.items():
            rule = properties[name]
            expected = rule.get("type")
            if expected == "string" and not isinstance(value, str):
                return "%s must be a string" % name
            if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                return "%s must be an integer" % name
            if "enum" in rule and value not in rule["enum"]:
                return "%s is not in the allowlist" % name
            if expected == "integer" and "minimum" in rule and value < rule["minimum"]:
                return "%s is below the minimum" % name
            if expected == "integer" and "maximum" in rule and value > rule["maximum"]:
                return "%s exceeds the maximum" % name
        return None

    def call(self, name: str, arguments: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        arguments = dict(arguments or {})
        spec = self._tools.get(name)
        if spec is None:
            raise ToolError("Unknown tool: " + name)
        self.audit.record("tool_requested", tool=name, risk=spec.risk, arguments=arguments)
        self.observer("tool_requested", {"tool": name, "risk": spec.risk, "arguments": arguments})
        validation_error = self._validate_arguments(spec, arguments)
        if validation_error:
            result = {"ok": False, "error": validation_error, "error_type": "ValidationError"}
            self.audit.record("tool_result", tool=name, result=result)
            self.observer("tool_result", {"tool": name, "result": result})
            return result
        if spec.risk == "write":
            approved = self.approval(name, arguments)
            self.audit.record("tool_approval", tool=name, approved=approved)
            if not approved:
                result = {"ok": False, "error": "Operator rejected the state-changing action"}
                self.observer("tool_rejected", {"tool": name})
                return result
        try:
            result = spec.handler(**arguments)
            wrapped = {"ok": True, "result": result}
        except Exception as exc:
            wrapped = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
        self.audit.record("tool_result", tool=name, result=wrapped)
        self.observer("tool_result", {"tool": name, "result": wrapped})
        return wrapped

    def call_json(self, name: str, arguments_json: str) -> str:
        try:
            arguments = json.loads(arguments_json or "{}")
        except json.JSONDecodeError as exc:
            result = {"ok": False, "error": "Invalid JSON arguments: %s" % exc}
            return json.dumps(result, sort_keys=True)
        return json.dumps(self.call(name, arguments), sort_keys=True, default=str)
