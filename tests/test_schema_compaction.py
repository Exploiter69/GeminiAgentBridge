from __future__ import annotations

import json
import unittest

from gemini_web2api.protocol import validate_tool_calls
from gemini_web2api.tool_schema import normalize_tool_definitions, tool_schema_size


class SchemaCompactionTests(unittest.TestCase):
    def _tool(self):
        return {
            "type": "function",
            "function": {
                "name": "configure",
                "description": "A deliberately long description that may be shortened during compaction. " * 8,
                "parameters": {
                    "type": "object",
                    "description": "Parameter description",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["fast", "safe"],
                            "default": "safe",
                            "minLength": 4,
                            "maxLength": 4,
                            "pattern": "^(fast|safe)$",
                            "format": "text",
                        },
                        "count": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 5,
                            "default": 1,
                        },
                        "items": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["A", "B"]},
                            "minItems": 1,
                            "maxItems": 3,
                            "uniqueItems": True,
                        },
                    },
                    "required": ["mode"],
                    "additionalProperties": False,
                    "anyOf": [
                        {"required": ["mode"]},
                        {"required": ["count"]},
                    ],
                    "oneOf": [{"properties": {"mode": {"const": "fast"}}}],
                    "allOf": [{"properties": {"count": {"type": "integer"}}}],
                    "nullable": False,
                    "default": {"mode": "safe", "count": 1},
                    "x-provider-constraint": {"enabled": True},
                },
            },
        }

    def test_compaction_preserves_semantic_schema_surface(self):
        original = self._tool()
        compacted = normalize_tool_definitions([original], max_chars=200)
        self.assertEqual(len(compacted), 1)

        schema = compacted[0]["parameters"]
        expected = {
            "type": "object",
            "properties": schema["properties"],
            "required": ["mode"],
            "additionalProperties": False,
            "anyOf": schema["anyOf"],
            "oneOf": schema["oneOf"],
            "allOf": schema["allOf"],
            "nullable": False,
            "default": {"mode": "safe", "count": 1},
            "x-provider-constraint": {"enabled": True},
        }
        for key, value in expected.items():
            self.assertEqual(schema[key], value)

        mode = schema["properties"]["mode"]
        self.assertEqual(mode["type"], "string")
        self.assertEqual(mode["enum"], ["fast", "safe"])
        self.assertEqual(mode["default"], "safe")
        self.assertEqual(mode["minLength"], 4)
        self.assertEqual(mode["maxLength"], 4)
        self.assertEqual(mode["pattern"], "^(fast|safe)$")
        self.assertEqual(mode["format"], "text")

        items = schema["properties"]["items"]
        self.assertEqual(items["items"]["enum"], ["A", "B"])
        self.assertEqual(items["minItems"], 1)
        self.assertEqual(items["maxItems"], 3)
        self.assertTrue(items["uniqueItems"])

    def test_original_and_compacted_schema_keep_same_validity_for_representative_calls(self):
        original = self._tool()
        compacted = normalize_tool_definitions([original], max_chars=200)

        samples = [
            {"mode": "fast", "count": 2, "items": ["A"]},
            {"mode": "safe"},
            {"mode": "slow"},
            {"mode": "fast", "unexpected": True},
            {"count": 2},
            {"mode": 5},
        ]

        for arguments in samples:
            call = [{
                "id": "call_test",
                "type": "function",
                "function": {
                    "name": "configure",
                    "arguments": json.dumps(arguments),
                },
            }]
            original_errors = bool(validate_tool_calls(call, [original]))
            compacted_errors = bool(validate_tool_calls(call, compacted))
            self.assertEqual(
                original_errors,
                compacted_errors,
                msg=f"validity changed for arguments={arguments!r}",
            )

    def test_tiny_budget_does_not_delete_semantic_constraints(self):
        compacted = normalize_tool_definitions([self._tool()], max_chars=1)
        self.assertTrue(compacted)
        self.assertGreater(tool_schema_size(compacted), 1)
        schema = compacted[0]["parameters"]
        self.assertEqual(schema["required"], ["mode"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["mode"]["enum"], ["fast", "safe"])
        self.assertEqual(schema["properties"]["count"]["default"], 1)

    def test_cosmetic_metadata_can_shrink_without_removing_tools(self):
        original = self._tool()
        compacted = normalize_tool_definitions([original], max_chars=500)
        self.assertEqual(compacted[0]["name"], "configure")
        self.assertLess(len(compacted[0]["description"]), len(original["function"]["description"]))
        self.assertNotIn("title", compacted[0]["parameters"])
        self.assertNotIn("$schema", compacted[0]["parameters"])
        self.assertIn("default", compacted[0]["parameters"])


if __name__ == "__main__":
    unittest.main()
