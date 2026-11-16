import json
import tempfile
import unittest
from pathlib import Path

from autonomous_network_agent.agent import DeterministicAgent, OpenAIResponsesAgent
from autonomous_network_agent.audit import AuditLogger
from autonomous_network_agent.backends import DemoNetworkBackend
from autonomous_network_agent.tools import ToolRegistry


class AgentTestCase(unittest.TestCase):
    def make_agent(self, approve=True):
        directory = Path(tempfile.mkdtemp())
        audit = AuditLogger(directory)
        backend = DemoNetworkBackend()
        tools = ToolRegistry(backend, audit, lambda _name, _args: approve)
        return backend, audit, tools, DeterministicAgent(tools, audit)

    def test_detect_repair_and_verify(self):
        backend, audit, _tools, agent = self.make_agent(approve=True)
        backend.inject_failure("upf")
        reply = agent.run("Operate the network, diagnose failures, and repair them safely")
        self.assertIn("Recovery verified", reply)
        self.assertEqual("running", backend.states["upf"])
        requested = [event.get("tool") for event in audit.events if event["event"] == "tool_requested"]
        self.assertEqual(
            [
                "get_network_status",
                "get_component_logs",
                "restart_component",
                "get_network_status",
                "get_ue_status",
            ],
            requested,
        )

    def test_rejected_mutation_is_not_reported_as_recovered(self):
        backend, _audit, _tools, agent = self.make_agent(approve=False)
        backend.inject_failure("upf")
        reply = agent.run("Heal the network")
        self.assertIn("not verified", reply)
        self.assertEqual("stopped", backend.states["upf"])

    def test_openai_tool_loop_uses_registry(self):
        backend, audit, tools, _agent = self.make_agent(approve=True)
        responses = [
            {
                "output": [
                    {
                        "type": "function_call",
                        "name": "get_network_status",
                        "arguments": "{}",
                        "call_id": "call_1",
                    }
                ]
            },
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "The network is healthy."}],
                    }
                ],
                "output_text": "The network is healthy.",
            },
        ]
        payloads = []

        def transport(payload):
            payloads.append(payload)
            return responses.pop(0)

        agent = OpenAIResponsesAgent(tools, audit, "test-model", transport=transport)
        reply = agent.run("Check the network")
        self.assertEqual("The network is healthy.", reply)
        self.assertEqual(2, len(payloads))
        function_output = payloads[1]["input"][-1]
        self.assertEqual("function_call_output", function_output["type"])
        parsed = json.loads(function_output["output"])
        self.assertTrue(parsed["ok"])
        self.assertTrue(backend.get_network_status()["healthy"])


if __name__ == "__main__":
    unittest.main()
