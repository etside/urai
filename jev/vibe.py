#!/usr/bin/env python3
"""Urai Vibe Coder — natural-language → code → run → iterate loop.

Best practices from clawd-code audit:
- Tool registry pattern (extensible)
- Bash safety patterns (no rm -rf /, no sudo, etc.)
- Path containment (only write within workspace)
- Tool result summarization (keep context small)
- Microcompact: strip images before sending to LLM

Usage:
    urai vibe "build a FastAPI todo app with SQLite"
    urai vibe "fix the login bug" --workspace /path/to/project
    urai vibe --plan "add dark mode to the dashboard"   # plan only, no execute
"""

from __future__ import annotations
import json, os, re, subprocess, sys, time
from pathlib import Path

# --- Safety patterns (from clawd-code audit) ---
_DANGEROUS = [
    re.compile(r'\bsudo\b', re.I),
    re.compile(r'\bshutdown\b', re.I),
    re.compile(r'\breboot\b', re.I),
    re.compile(r'\bmkfs\b', re.I),
    re.compile(r'\bdd\b\s+if=', re.I),
    re.compile(r'\brm\b.*-rf\s+/\s*$', re.I),
    re.compile(r':\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:'),  # fork bomb
    re.compile(r'curl.*\|\s*(ba)?sh', re.I),  # pipe to shell
]

TOOLS = [
    {'name': 'write_file', 'desc': 'Write or overwrite a file'},
    {'name': 'read_file',  'desc': 'Read a file'},
    {'name': 'bash',       'desc': 'Run a shell command (safe subset)'},
    {'name': 'search',     'desc': 'Grep for a pattern in files'},
    {'name': 'plan',       'desc': 'Output a plan without executing'},
    {'name': 'done',       'desc': 'Task complete'},
]


class SafetyError(RuntimeError): pass
class PathError(RuntimeError): pass


def _check_bash_safety(cmd: str):
    for pat in _DANGEROUS:
        if pat.search(cmd):
            raise SafetyError(f'Refusing dangerous command: {cmd[:80]}')


def _check_path(path: str, workspace: Path):
    p = Path(path).expanduser().resolve()
    try:
        p.relative_to(workspace)
    except ValueError:
        raise PathError(f'Path {path} is outside workspace {workspace}')
    return p


def _summarize_result(tool: str, result: str, max_chars: int = 800) -> str:
    """Keep tool results compact (from clawd-code audit — tool result summarization)."""
    if len(result) <= max_chars:
        return result
    head = result[:max_chars // 2]
    tail = result[-(max_chars // 2):]
    return f'{head}\n... [{len(result) - max_chars} chars omitted] ...\n{tail}'


def _exec_tool(name: str, args: dict, workspace: Path) -> str:
    if name == 'write_file':
        path = _check_path(args['path'], workspace)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args['content'], encoding='utf-8')
        return f'wrote {path} ({len(args["content"])} chars)'

    elif name == 'read_file':
        path = _check_path(args['path'], workspace)
        if not path.exists():
            return f'file not found: {path}'
        content = path.read_text(encoding='utf-8', errors='replace')
        return _summarize_result('read_file', content)

    elif name == 'bash':
        cmd = args.get('command', '')
        _check_bash_safety(cmd)
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           cwd=str(workspace), timeout=args.get('timeout', 30))
        out = (r.stdout + r.stderr).strip()
        return _summarize_result('bash', out or f'exit {r.returncode}')

    elif name == 'search':
        pat = args.get('pattern', '')
        path = str(workspace)
        r = subprocess.run(['grep', '-r', '-n', '-l', pat, path],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or 'no matches'

    elif name == 'plan':
        return args.get('steps', '')

    elif name == 'done':
        return '__DONE__'

    return f'unknown tool: {name}'


def vibe_session(task: str, workspace: str | None = None,
                 plan_only: bool = False, max_steps: int = 20,
                 verbose: bool = True) -> dict:
    """Run a vibe coding session. Returns {steps, files_written, summary}."""
    from .engine import complete
    from .backends import LlamaServerBackend

    ws = Path(workspace or os.getcwd()).expanduser().resolve()
    ws.mkdir(parents=True, exist_ok=True)

    tools_desc = '\n'.join(f'  {t["name"]}: {t["desc"]}' for t in TOOLS)
    system = (
        f'You are Urai Vibe Coder. Workspace: {ws}\n'
        f'Available tools (call ONE per turn as JSON object):\n{tools_desc}\n'
        'Format: {{"tool": "name", "args": {{...}}}}\n'
        'Rules: 1) Only write within workspace. 2) Run tests after writing code. '
        '3) Call done when the task is complete. 4) Max steps: ' + str(max_steps)
    )
    if plan_only:
        system += '\n5) Only produce a plan. Use the plan tool, then done.'

    history = []
    steps = []
    files_written = []
    backend = LlamaServerBackend()

    for step in range(max_steps):
        msgs = [{'role': 'system', 'content': system}]
        msgs.append({'role': 'user', 'content': task if step == 0 else 'Continue.'})
        msgs.extend(history)

        try:
            result = complete(backend, msgs, max_tokens=1024, temperature=0.2)
            reply = result['content'].strip()
        except Exception as e:
            break

        # Parse tool call from reply
        tool_call = None
        for line in reply.split('\n'):
            line = line.strip()
            if line.startswith('{') and '"tool"' in line:
                try:
                    tool_call = json.loads(line)
                    break
                except json.JSONDecodeError:
                    pass
        # Also try to find JSON block
        if not tool_call:
            m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', reply, re.DOTALL)
            if m:
                try:
                    tool_call = json.loads(m.group(1))
                except:
                    pass

        if not tool_call:
            steps.append({'step': step + 1, 'type': 'text', 'content': reply})
            history.append({'role': 'assistant', 'content': reply})
            history.append({'role': 'user', 'content': 'Please respond with a tool call JSON.'})
            continue

        tool_name = tool_call.get('tool', 'done')
        tool_args = tool_call.get('args', {})

        try:
            tool_result = _exec_tool(tool_name, tool_args, ws)
        except (SafetyError, PathError) as e:
            tool_result = f'BLOCKED: {e}'

        if verbose:
            print(f'  [{step+1}] {tool_name} → {tool_result[:120]}')

        if tool_name == 'write_file' and 'BLOCKED' not in tool_result:
            files_written.append(tool_args.get('path', ''))

        steps.append({'step': step+1, 'tool': tool_name, 'args': tool_args, 'result': tool_result})
        history.append({'role': 'assistant', 'content': reply})
        history.append({'role': 'user', 'content': f'Tool result: {_summarize_result(tool_name, tool_result)}'})

        if tool_result == '__DONE__':
            break

    return {'steps': steps, 'files_written': files_written,
            'workspace': str(ws), 'task': task}
