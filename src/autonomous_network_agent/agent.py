import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from .audit import AuditLogger
from .tools import ToolRegistry


class AgentError(RuntimeError):
    pass


class DeterministicAgent:
    """A predictable rehearsal agent that uses the production tool registry."""

    def __init__(self, tools: ToolRegistry, audit: AuditLogger) -> None:
        self.tools = tools
        self.audit = audit

    def _component_in(self, prompt: str) -> Optional[str]:
        lowered = prompt.lower()
        for component in self.tools.backend.components:
            if component.lower() in lowered:
                return component
        return None

    def run(self, prompt: str) -> str:
        self.audit.record("user_message", content=prompt)
        lowered = prompt.lower()
        if "throughput" in lowered or "iperf" in lowered:
            result = self.tools.call("run_throughput_test", {"duration_seconds": 3})
            return self._record_reply("Throughput test result:\n" + json.dumps(result, indent=2))
        if "log" in lowered and not any(
            word in lowered for word in ("heal", "repair", "fix", "operate", "ensure", "diagnose")
        ):
            component = self._component_in(prompt) or "amf"
            result = self.tools.call("get_component_logs", {"component": component, "tail": 80})
            return self._record_reply("Recent %s logs:\n%s" % (component, json.dumps(result, indent=2)))
        if any(word in lowered for word in ("heal", "repair", "fix", "operate", "ensure", "diagnose")):
            return self._heal()
        if "status" in lowered or "health" in lowered or "ue" in lowered:
            status = self.tools.call("get_network_status")
            ue = self.tools.call("get_ue_status")
            return self._record_reply(
                "Network status:\n%s\nUE status:\n%s"
                % (json.dumps(status, indent=2), json.dumps(ue, indent=2))
            )
        return self._record_reply(
            "I can inspect status and logs, diagnose and heal an unhealthy network, or run a throughput test. "
            "Try: 'Ensure all UEs are registered and repair safe failures.'"
        )

    def _heal(self) -> str:
        before = self.tools.call("get_network_status")
        if not before.get("ok"):
            return self._record_reply("I could not inspect the network: " + json.dumps(before))
        unhealthy = before["result"].get("unhealthy_components", [])
        if not unhealthy:
            ue = self.tools.call("get_ue_status")
            return self._record_reply(
                "The network is healthy; no mutation was needed. Verification:\n"
                + json.dumps(ue, indent=2)
            )

        actions: List[Dict[str, Any]] = []
        for component in unhealthy:
            evidence = self.tools.call(
                "get_component_logs", {"component": component, "tail": 80}
            )
            repair = self.tools.call("restart_component", {"component": component})
            actions.append({"component": component, "evidence": evidence, "repair": repair})
        after = self.tools.call("get_network_status")
        ue = self.tools.call("get_ue_status")
        recovered = bool(
            after.get("ok")
            and after["result"].get("healthy")
            and ue.get("ok")
            and ue["result"].get("registered")
            and ue["result"].get("pdu_session_established")
        )
        conclusion = "Recovery verified." if recovered else "Recovery was not verified; escalation required."
        return self._record_reply(
            "%s\nActions and evidence:\n%s\nPost-action network status:\n%s\nPost-action UE status:\n%s"
            % (
                conclusion,
                json.dumps(actions, indent=2),
                json.dumps(after, indent=2),
                json.dumps(ue, indent=2),
            )
        )

    def _record_reply(self, reply: str) -> str:
        self.audit.record("assistant_message", content=reply, brain="deterministic")
        return reply


Transport = Callable[[Dict[str, Any]], Dict[str, Any]]


class OpenAIResponsesAgent:
    """Minimal Responses API tool loop using the same guarded local tools."""

    def __init__(
        self,
        tools: ToolRegistry,
        audit: AuditLogger,
        model: str,
        api_key: Optional[str] = None,
        transport: Optional[Transport] = None,
    ) -> None:
        self.tools = tools
        self.audit = audit
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.transport = transport or self._http_transport
        self.history: List[Dict[str, Any]] = []

    def _http_transport(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key:
            raise AgentError("OPENAI_API_KEY is required for --brain openai")
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AgentError("OpenAI API error %s: %s" % (exc.code, detail)) from exc
        except urllib.error.URLError as exc:
            raise AgentError("OpenAI API connection failed: %s" % exc.reason) from exc

    @staticmethod
    def _text(response: Dict[str, Any]) -> str:
        if response.get("output_text"):
            return str(response["output_text"])
        parts: List[str] = []
        for item in response.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") in ("output_text", "text") and content.get("text"):
                        parts.append(str(content["text"]))
        return "\n".join(parts)

    def run(self, prompt: str) -> str:
        self.audit.record("user_message", content=prompt)
        working_input = list(self.history)
        working_input.append({"role": "user", "content": prompt})
        instructions = (
            "You are a cautious autonomous 5G network operator. Inspect before acting. "
            "Use only the supplied tools, prefer read-only evidence, never invent tool results, "
            "and never claim recovery until get_network_status and get_ue_status verify it. "
            "State-changing tools are independently approval-gated by the application. "
            "If an action is rejected or verification fails, explain and escalate."
        )
        for _iteration in range(8):
            payload = {
                "model": self.model,
                "instructions": instructions,
                "tools": self.tools.model_schemas(),
                "input": list(working_input),
                "parallel_tool_calls": False,
            }
            response = self.transport(payload)
            outputs = response.get("output", [])
            working_input.extend(outputs)
            calls = [item for item in outputs if item.get("type") == "function_call"]
            if not calls:
                reply = self._text(response) or "The model returned no message."
                self.history = working_input
                self.audit.record("assistant_message", content=reply, brain="openai", model=self.model)
                return reply
            for call in calls:
                output = self.tools.call_json(str(call.get("name")), str(call.get("arguments", "{}")))
                working_input.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.get("call_id"),
                        "output": output,
                    }
                )
        raise AgentError("Tool loop exceeded eight iterations")
