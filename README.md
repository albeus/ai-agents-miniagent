# ai-agents-miniagent

A deliberately small Python agent harness for learning how LLM tool calling works: the model proposes a tool call, Python validates and runs it, and the result goes back to the model.

> **Part of the [AI Agents Lab](https://github.com/albeus/ai-agents-lab).** This is a learning exercise, not a production agent or a security boundary. See [Safety notice](#safety-notice) before running it.

## What this demonstrates

The agent talks to a local Ollama model through its OpenAI-compatible API and exposes three constrained tools:

- `run_shell(cmd)` runs a limited set of intended read-only diagnostic commands.
- `read_file(path)` reads a text file only beneath an approved directory.
- `search_notes(query)` searches approved Markdown notes and runbooks.

The model never executes anything itself. It returns a request for a named tool with arguments. The Python harness decides whether the request is acceptable, performs the action, and returns the result to the model.

## Safety notice

- `run_shell` currently uses `shell=True`. Its prefix allowlist and metacharacter rejection are **learning controls, not a robust security boundary**.
- An allowed prefix can still return sensitive data. For example, `kubectl get` can read Kubernetes Secrets if your kubeconfig allows it. Use a lab cluster with a least-privilege, read-only identity, or do not install `kubectl`.
- Run it only on a disposable machine, VM or container, with non-sensitive data and no production credentials.
- The lab notes directory must contain only non-sensitive material: no passwords, API keys, private keys, production host lists or confidential runbooks.

## Agent loop

1. Add the user request to the conversation history.
2. Send the history and the tool schemas to the model.
3. Inspect the model response.
4. If the model requests a tool, validate the tool name and arguments, execute the permitted tool, add the result to the history, and call the model again.
5. If the model returns a normal response, display it and stop.

This is the basic pattern behind an agent: a model, a tool loop, and a policy for what enters its context and what actions it may take.

```text
User request
     │
     ▼
Harness assembles history and tool schemas
     │
     ▼
Model produces a response
     │
     ├── Final answer ───────────────► Display and stop
     │
     └── Tool request
              │
              ▼
       Harness validates it
              │
              ▼
       Tool implementation runs
              │
              ▼
       Result added to history
              │
              └────────────────────► Call model again
```

## Requirements

- Python 3.12 or later.
- [Ollama](https://ollama.com/) running locally.
- A tool-calling capable Ollama model, currently configured as `qwen3:8b`.
- Optional: `kubectl`, only to try the Kubernetes diagnostic command (see the safety notice).
- Local test notes in `~/agent-lab/readable` (created below).

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If you prefer Pipenv, `pipenv install && pipenv shell` also works.

Start Ollama and pull the configured model:

```bash
ollama serve                # in one terminal, if not already running
ollama pull qwen3:8b        # in another terminal
```

Confirm the OpenAI-compatible endpoint responds:

```bash
curl -s http://localhost:11434/v1/models
```

## Create local test data

The file-read and note-search tools are restricted to `~/agent-lab/readable`.

```bash
mkdir -p ~/agent-lab/readable

cat > ~/agent-lab/readable/ssh-triage.md <<'EOF'
# SSH triage

Check failed systemd units:

systemctl --failed

Review recent SSH service logs:

journalctl -u ssh -n 50 --no-pager

Check whether port 22 is listening:

ss -lntp | grep ':22'
EOF

cat > ~/agent-lab/readable/kubernetes-pods.md <<'EOF'
# Kubernetes pod triage

List pods in a namespace:

kubectl get pods --namespace <namespace>

Inspect a failing pod:

kubectl describe pod <pod-name> --namespace <namespace>

Review container logs:

kubectl logs <pod-name> --namespace <namespace> --all-containers
EOF
```

Verify the test data:

```bash
find ~/agent-lab/readable -type f -name '*.md' -print
grep -Rni --include='*.md' 'systemctl' ~/agent-lab/readable
```

## Running the agent

```bash
python miniagent.py "User prompt / Task"
```

Example tasks:

```text
Check the free disk space on this machine.
Search the runbooks for systemctl and summarise the recommended check.
Read the SSH triage runbook and explain the first diagnostic action.
Check whether any systemd units have failed.
```

Small local models sometimes produce malformed tool calls. If a run fails, try rephrasing the task or a different tool-calling model before assuming the harness is at fault.

## Tool boundaries

### Shell commands

`run_shell` accepts only commands whose text begins with one of these configured prefixes:

```python
ALLOWED_PREFIXES = (
    "df",
    "free",
    "systemctl status",
    "journalctl -n",
    "kubectl get",
)
```

It also rejects shell metacharacters, applies a 10-second timeout, and truncates output to about 2,000 characters before returning it to the model.

These controls reduce the chance that a bad model decision or hostile text causes arbitrary command execution. They do not remove it: prefix matching is coarse (for example, `df` also matches any command that merely starts with those letters), and the implementation still relies on `shell=True`.

### File access

`read_file` resolves the requested path and verifies that it stays below `~/agent-lab/readable`. Reads outside that directory are rejected, and file contents are truncated before they are sent to the model.

### Note search

`search_notes` searches only Markdown files below the approved directory. It returns matching file paths, line numbers and lines, up to a maximum number of matches.

## Safety lessons

Model tool calls must be treated as untrusted requests, even when they come from a helpful user prompt.

Controls in place:

- Intended read-only command prefixes.
- Rejection of shell metacharacters.
- Command timeouts.
- Output truncation.
- A restricted filesystem root.
- Markdown-only search.
- No arbitrary network, SSH, credential or write-operation tool.

Prompt injection can arrive in user input or in content the agent reads. A runbook might contain text that tries to persuade the model to access a secret. Tool validation and least-privilege access limit what such an instruction can achieve, but only if the tools themselves are safe.

## Limitations and next improvements

This harness does not yet provide:

- A hard iteration limit for the model/tool loop.
- Detection of repeated identical tool calls.
- A wall-clock limit for an agent run.
- Structured JSONL logs or distributed traces.
- Human approval before sensitive operations.
- Authentication, authorisation or multi-user isolation.
- Container sandboxing or network egress controls.
- Strict command parsing with `shell=False`.

The most useful next hardening step is to replace shell-string execution with fixed executable-and-argument lists, so safety no longer depends on filtering metacharacters. Loop and wall-clock limits come next.

## Relationship to the rest of the lab

`miniagent` is an agent harness: it owns the model conversation and executes its own tools locally. It is **not** currently an MCP client.

[`ai-agents-mcp-itsops`](https://github.com/albeus/ai-agents-mcp-itsops) is a separate MCP server that publishes narrow tools through a standard protocol so an MCP-compatible client can discover and call them. Both projects apply the same principle (narrow, well-described capabilities with explicit validation and bounded output); the difference is where the tool loop and the client/server boundary sit.

See the [lab index](https://github.com/albeus/ai-agents-lab) for the suggested reading order and the other projects.

