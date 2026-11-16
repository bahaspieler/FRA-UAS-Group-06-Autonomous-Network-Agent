import tempfile
import unittest
from pathlib import Path

from autonomous_network_agent.audit import AuditLogger
from autonomous_network_agent.backends import DemoNetworkBackend
from autonomous_network_agent.tools import ToolError, ToolRegistry


class ToolRegistryTestCase(unittest.TestCase):
    def setUp(self):
        self.backend = DemoNetworkBackend()
        self.audit = AuditLogger(Path(tempfile.mkdtemp()))
        self.registry = ToolRegistry(self.backend, self.audit, lambda _name, _args: True)

    def test_schemas_are_strict(self):
        schemas = self.registry.model_schemas()
        self.assertEqual(5, len(schemas))
        for schema in schemas:
            self.assertTrue(schema["strict"])
            self.assertFalse(schema["parameters"]["additionalProperties"])

    def test_unknown_tool_is_rejected(self):
        with self.assertRaises(ToolError):
            self.registry.call("arbitrary_shell", {"command": "whoami"})

    def test_component_allowlist_is_enforced(self):
        result = self.registry.call("restart_component", {"component": "not-a-service"})
        self.assertFalse(result["ok"])
        self.assertEqual("ValidationError", result["error_type"])

    def test_numeric_bounds_are_enforced_by_application(self):
        result = self.registry.call("run_throughput_test", {"duration_seconds": 999})
        self.assertFalse(result["ok"])
        self.assertIn("maximum", result["error"])

    def test_additional_arguments_are_rejected(self):
        result = self.registry.call("get_network_status", {"command": "whoami"})
        self.assertFalse(result["ok"])
        self.assertIn("Unexpected", result["error"])


if __name__ == "__main__":
    unittest.main()
