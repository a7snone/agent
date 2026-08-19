"""Tool definitions and implementations for the agent.

Each tool has two parts:
1. A JSON-schema entry in TOOLS (tells Claude what the tool does and its inputs).
2. A Python function in TOOL_FUNCTIONS with the same name (does the actual work).

To add a new tool: write the function, then add its schema to TOOLS and
register it in TOOL_FUNCTIONS.
"""

from __future__ import annotations

import ast
import datetime
import operator
import os

# Directory the file tools are allowed to touch, so the agent can't read/write
# arbitrary paths on the machine.
SANDBOX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sandbox")
os.makedirs(SANDBOX_DIR, exist_ok=True)


def _resolve_sandbox_path(filename: str) -> str:
    path = os.path.abspath(os.path.join(SANDBOX_DIR, filename))
    if not path.startswith(SANDBOX_DIR + os.sep) and path != SANDBOX_DIR:
        raise ValueError("Path escapes the sandbox directory")
    return path


_ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPERATORS:
        return _ALLOWED_OPERATORS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPERATORS:
        return _ALLOWED_OPERATORS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"Unsupported expression: {ast.dump(node)}")


def calculator(expression: str) -> str:
    """Safely evaluate a basic arithmetic expression (+ - * / ** %)."""
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_node(tree.body)
        return str(result)
    except Exception as exc:
        return f"Error: {exc}"


def get_current_time(timezone: str = "UTC") -> str:
    """Return the current date/time. Only UTC is supported in this skeleton."""
    if timezone.upper() != "UTC":
        return "Error: only 'UTC' is supported in this skeleton."
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def read_file(filename: str) -> str:
    """Read a text file from the sandbox directory."""
    try:
        path = _resolve_sandbox_path(filename)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as exc:
        return f"Error: {exc}"


def write_file(filename: str, content: str) -> str:
    """Write text content to a file in the sandbox directory."""
    try:
        path = _resolve_sandbox_path(filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote {len(content)} characters to {filename}"
    except Exception as exc:
        return f"Error: {exc}"


def list_files(_: str = "") -> str:
    """List files currently in the sandbox directory."""
    files = sorted(os.listdir(SANDBOX_DIR))
    return "\n".join(files) if files else "(empty)"


TOOLS = [
    {
        "name": "calculator",
        "description": "Evaluate a basic arithmetic expression, e.g. '(3 + 4) * 2'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "The arithmetic expression to evaluate."}
            },
            "required": ["expression"],
        },
    },
    {
        "name": "get_current_time",
        "description": "Get the current date and time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "timezone": {"type": "string", "description": "Timezone name. Only 'UTC' is supported."}
            },
            "required": [],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a text file from the sandbox directory.",
        "input_schema": {
            "type": "object",
            "properties": {"filename": {"type": "string", "description": "Name of the file to read."}},
            "required": ["filename"],
        },
    },
    {
        "name": "write_file",
        "description": "Write text content to a file in the sandbox directory (creates or overwrites it).",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Name of the file to write."},
                "content": {"type": "string", "description": "Text content to write."},
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "List the files currently available in the sandbox directory.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]

TOOL_FUNCTIONS = {
    "calculator": calculator,
    "get_current_time": get_current_time,
    "read_file": read_file,
    "write_file": write_file,
    "list_files": list_files,
}
