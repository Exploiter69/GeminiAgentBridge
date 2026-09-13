import json
import unittest

from gemini_web2api.config import DEFAULT_CONFIG
from gemini_web2api.planner import PlannerProposal, propose, proposal_to_tool_call


def tool(name, description, properties=None, required=None):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties or {},
                           "required": required or [], "additionalProperties": False}}}

READ = tool("read_file", "Read a file from the workspace.", {"path": {"type": "string"}}, ["path"])
SEARCH = tool("search", "Search the codebase for a query.", {"query": {"type": "string"}}, ["query"])
EDIT = tool("edit_file", "Edit or modify a file.", {"path": {"type": "string"}}, ["path"])
LIST = tool("list_files", "List files in a directory.")


class PlannerPolicyTests(unittest.TestCase):
    def test_planner_is_off_by_default(self):
        self.assertFalse(DEFAULT_CONFIG["planner_enabled"])

    def test_obvious_read_is_high_confidence(self):
        p = propose('Read "sample.txt"', [READ])
        self.assertEqual((p.confidence, p.tool_name), ("high", "read_file"))
        self.assertEqual(p.arguments, {"path": "sample.txt"})
        self.assertTrue(p.should_synthesize)

    def test_obvious_search_is_high_confidence(self):
        p = propose('Search for "TODO"', [SEARCH])
        self.assertEqual((p.confidence, p.tool_name), ("high", "search"))
        self.assertEqual(p.arguments, {"query": "TODO"})

    def test_obvious_list_is_high_confidence(self):
        p = propose("List files", [LIST])
        self.assertEqual((p.confidence, p.tool_name), ("high", "list_files"))
        self.assertEqual(p.arguments, {})

    def test_obvious_edit_requires_explicit_path(self):
        p = propose('Edit "app.py"', [EDIT])
        self.assertEqual(p.confidence, "high")
        self.assertEqual(p.arguments, {"path": "app.py"})

    def test_edit_with_missing_content_stays_medium(self):
        edit = tool("edit_file", "Edit or modify a file.",
                    {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"])
        p = propose('Edit "app.py"', [edit])
        self.assertEqual(p.confidence, "medium")
        self.assertFalse(p.should_synthesize)

    def test_ambiguous_request_is_not_synthesized(self):
        p = propose("Help me with the project", [READ, SEARCH, EDIT])
        self.assertEqual(p.confidence, "medium")
        self.assertFalse(p.should_synthesize)
        self.assertIsNone(proposal_to_tool_call(p))

    def test_multi_step_request_is_low_confidence(self):
        p = propose('Search for "TODO" then edit app.py', [SEARCH, EDIT])
        self.assertEqual(p.confidence, "low")
        self.assertFalse(p.should_synthesize)

    def test_wrong_path_is_never_invented_from_grounding(self):
        grounding = type("Grounding", (), {"requested_cwd": "/tmp/project"})()
        p = propose("Read the current file", [READ], grounding=grounding)
        self.assertNotEqual(p.confidence, "high")
        self.assertIsNone(proposal_to_tool_call(p))

    def test_multiple_matching_tools_drop_to_medium(self):
        read2 = tool("cat_file", "Read a file from the workspace.", {"path": {"type": "string"}}, ["path"])
        p = propose('Read "sample.txt"', [READ, read2])
        self.assertEqual(p.confidence, "medium")
        self.assertIsNone(proposal_to_tool_call(p))

    def test_required_arguments_block_unsafe_list_proposal(self):
        list_dir = tool("list_files", "List files in a directory.", {"path": {"type": "string"}}, ["path"])
        p = propose("List files", [list_dir])
        self.assertEqual(p.confidence, "medium")
        self.assertIsNone(proposal_to_tool_call(p))

    def test_serialization_uses_strict_protocol(self):
        p = propose('Read "sample.txt"', [READ])
        raw = proposal_to_tool_call(p)
        body = raw.split("@@TOOL_CALL@@\n", 1)[1].split("\n@@END_TOOL_CALL@@", 1)[0]
        self.assertEqual(json.loads(body), {"name": "read_file", "arguments": {"path": "sample.txt"}})

    def test_planner_never_executes_tools(self):
        p = propose('Read "sample.txt"', [READ])
        self.assertEqual(p.tool_name, "read_file")


class PlannerProposalTests(unittest.TestCase):
    def test_low_and_medium_are_explicitly_non_synthesizing(self):
        for p in (PlannerProposal("low", "uncertain"), PlannerProposal("medium", "needs clarification")):
            self.assertFalse(p.should_synthesize)
            self.assertIsNone(proposal_to_tool_call(p))


if __name__ == "__main__":
    unittest.main()
