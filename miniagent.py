import json
import requests
import subprocess
import time
from pathlib import Path
import sys

ALLOWED_PREFIXES = (
    "df",
    "free",
    "systemctl status",
    "journalctl -n",
    "kubectl get",
)

SHELL_METACHARACTERS = "&;|$<>`()\\!*?[]{}'\""

READ_ROOT = Path.home() / "agent-lab" / "readable"

def run_shell(cmd: str) -> str:
    if not cmd.startswith(ALLOWED_PREFIXES):
        return f"Error: command not allowed: {cmd}"

    if any(c in cmd for c in SHELL_METACHARACTERS):
        return "Error: command contains shell metacharacters"

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = result.stdout
        if len(output) > 2000:
            return output[:2000] + "\n... (truncated)"
        return output
    except subprocess.CalledProcessError as e:
        return f"Command failed with error:\n{e.stderr}"
    except subprocess.TimeoutExpired:
        return "Error: command exceeded 10-second timeout"


def read_file(path: str) -> str:
    try:
        target = Path(path).expanduser().resolve()
        root = READ_ROOT.resolve()
        target.relative_to(root)
    except ValueError:
        return "Error: path is outside the permitted read directory"

    if not target.is_file():
        return "Error: file does not exist or is not a regular file"

    try:
        content = target.read_text(errors="replace")
    except OSError as exc:
        return f"Error: could not read file: {exc}"

    if len(content) > 2000:
        return content[:2000] + "\n[Output truncated at 2000 characters]"

    return content

def search_notes(query: str) -> str:
    matches = []

    for note in READ_ROOT.rglob("*.md"):
        try:
            for number, line in enumerate(note.read_text(errors="replace").splitlines(), 1):
                if query.lower() in line.lower():
                    matches.append(f"{note.relative_to(READ_ROOT)}:{number}: {line}")
                    if len(matches) >= 20:
                        return "\n".join(matches)
        except OSError:
            continue

    return "\n".join(matches) if matches else "No matching notes found"


MODEL = "qwen3:8b"
OLLAMA_URL = "http://localhost:11434/v1/chat/completions"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run an allowlisted read-only diagnostic command.",
            "parameters": {
                "type": "object",
                "properties": {"cmd": {"type": "string"}},
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file beneath the approved directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "Search approved Markdown runbooks.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]

def call_model(messages: list[dict]) -> dict:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "messages": messages,
            "tools": TOOLS,
            "temperature": 0,
        },
        timeout=180,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]


TOOL_FUNCTIONS = {
    "run_shell": run_shell,
    "read_file": read_file,
    "search_notes": search_notes,
}

def run_agent(user_text: str) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a cautious IT operations assistant. "
                "Use tools only when needed. Never claim a tool result you did not receive."
            ),
        },
        {"role": "user", "content": user_text},
    ]

    started = time.monotonic()
    seen_calls = set()

    for iteration in range(1, 9):
        if time.monotonic() - started > 180:
            return "Stopped: 180-second wall-clock limit reached."

        assistant_message = call_model(messages)
        messages.append(assistant_message)

        tool_calls = assistant_message.get("tool_calls", [])

        # Debug output to stderr
        print(f"--- Iteration {iteration} ---", file=sys.stderr)
        if assistant_message.get("content"):
            print(f"Assistant: {assistant_message['content']}", file=sys.stderr)
        for tc in tool_calls:
            f = tc["function"]
        print(f"Tool request: {f['name']}({f['arguments']})", file=sys.stderr)
        print("Messages so far:", file=sys.stderr)
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            print(f"{role}: {content}", file=sys.stderr)
        # END Debug output

        if not tool_calls:
            return assistant_message.get("content", "")

        for tool_call in tool_calls:
            function = tool_call["function"]
            name = function["name"]

            try:
                arguments = json.loads(function["arguments"])
            except json.JSONDecodeError:
                result = "Error: tool arguments were not valid JSON."
            else:
                call_key = (name, json.dumps(arguments, sort_keys=True))

                if call_key in seen_calls:
                    return f"Stopped: repeated identical tool call: {name}"

                seen_calls.add(call_key)
                handler = TOOL_FUNCTIONS.get(name)

                if handler is None:
                    result = f"Error: unknown tool: {name}"
                else:
                    try:
                        result = handler(**arguments)
                    except TypeError:
                        result = f"Error: invalid arguments for tool: {name}"

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result,
                }
            )

    return "Stopped: maximum of 8 iterations reached."

def main() -> None:
    import sys
    if len(sys.argv) > 1:
        print(run_agent(" ".join(sys.argv[1:])))
        return
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text in {"exit", "quit"}:
            break
        if text:
            print(run_agent(text))

if __name__ == "__main__":
    main()
