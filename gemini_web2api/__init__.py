"""gemini-web2api: Gemini Web to OpenAI API proxy."""
__version__ = "1.1.0"

# Keep the public tools API stable while upgrading parsing centrally. Importing
# the package happens before server.py imports .tools, so this compatibility
# shim also covers existing callers without requiring a breaking API change.
from . import tools as _tools
from .protocol import parse_tool_calls_robust

_tools.parse_tool_calls = parse_tool_calls_robust
