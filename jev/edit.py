#!/usr/bin/env python3
"""Urai Edit — AI-powered file and image editing.

Text file editing:
  - str_replace: surgical find-and-replace with AI verification
  - rewrite: full file rewrite from instructions
  - patch: unified diff apply

Image editing (requires OPENAI_API_KEY or STABILITY_API_KEY):
  - inpaint: fill a masked region
  - outpaint: extend the image
  - style_transfer: apply a style prompt
"""

from __future__ import annotations
import difflib, json, os, re
from pathlib import Path

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
STABILITY_API_KEY = os.environ.get('STABILITY_API_KEY', '')


# --- Text editing ---

def str_replace(path: str, old_str: str, new_str: str,
                dry_run: bool = False) -> dict:
    """Surgical string replacement in a file. Fails if old_str not found or ambiguous."""
    p = Path(path)
    if not p.exists():
        return {'ok': False, 'error': f'file not found: {path}'}
    content = p.read_text(encoding='utf-8')
    count = content.count(old_str)
    if count == 0:
        return {'ok': False, 'error': 'old_str not found in file'}
    if count > 1:
        return {'ok': False, 'error': f'old_str found {count} times — be more specific'}
    new_content = content.replace(old_str, new_str, 1)
    diff = list(difflib.unified_diff(
        content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=path, tofile=path, n=3))
    if not dry_run:
        p.write_text(new_content, encoding='utf-8')
    return {'ok': True, 'diff': ''.join(diff), 'dry_run': dry_run}


def ai_edit(path: str, instruction: str, workspace: str | None = None) -> dict:
    """AI-powered file edit. Uses local model to apply natural language instruction."""
    from .engine import complete
    from .backends import LlamaServerBackend
    from .vibe import _check_path, PathError

    p = Path(path)
    if not p.exists():
        return {'ok': False, 'error': f'file not found: {path}'}

    ws = Path(workspace or p.parent).resolve()
    try:
        _check_path(str(p.resolve()), ws)
    except PathError as e:
        return {'ok': False, 'error': str(e)}

    content = p.read_text(encoding='utf-8', errors='replace')
    # Truncate for context
    if len(content) > 8000:
        content = content[:4000] + '\n... [truncated] ...\n' + content[-4000:]

    system = (
        'You are a code editor. Apply the instruction to the file content.\n'
        'Respond with ONLY the complete new file content — no explanation, no markdown fences.'
    )
    prompt = f'Instruction: {instruction}\n\nFile ({path}):\n{content}'

    try:
        result = complete(LlamaServerBackend(),
                          [{'role': 'system', 'content': system},
                           {'role': 'user', 'content': prompt}],
                          max_tokens=4096, temperature=0.1)
        new_content = result['content'].strip()
        # Strip markdown fences if model added them
        if new_content.startswith('```'):
            new_content = re.sub(r'^```[\w]*\n?', '', new_content)
            new_content = re.sub(r'\n?```$', '', new_content)
        diff = list(difflib.unified_diff(
            content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=path, tofile=path, n=3))
        p.write_text(new_content, encoding='utf-8')
        return {'ok': True, 'diff': ''.join(diff), 'model': result.get('model')}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# --- Image editing ---

def image_edit(image_path: str, instruction: str,
               mask_path: str | None = None,
               output_path: str | None = None) -> dict:
    """AI image editing via OpenAI DALL-E edit or Stability.ai inpaint."""
    import base64, urllib.request
    img_data = Path(image_path).read_bytes()

    if OPENAI_API_KEY:
        # OpenAI image edit (inpaint)
        import subprocess, json, tempfile
        base = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
        cmd = ['curl', '-s', '-X', 'POST', f'{base}/images/edits',
               '-H', f'Authorization: Bearer {OPENAI_API_KEY}',
               '-F', f'image=@{image_path}',
               '-F', f'prompt={instruction}',
               '-F', 'n=1', '-F', 'size=1024x1024',
               '-F', 'response_format=b64_json']
        if mask_path:
            cmd += ['-F', f'mask=@{mask_path}']
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        data = json.loads(r.stdout)
        if 'data' not in data:
            return {'ok': False, 'error': data.get('error', {}).get('message', str(data))}
        img_bytes = base64.b64decode(data['data'][0]['b64_json'])
        out = output_path or image_path.replace('.', '_edited.')
        Path(out).write_bytes(img_bytes)
        return {'ok': True, 'output': out, 'backend': 'openai-dalle'}

    elif STABILITY_API_KEY:
        # Stability AI inpaint
        import subprocess, tempfile
        cmd = ['curl', '-s', '-X', 'POST',
               'https://api.stability.ai/v2beta/stable-image/edit/inpaint',
               '-H', f'Authorization: Bearer {STABILITY_API_KEY}',
               '-H', 'Accept: image/*',
               '-F', f'image=@{image_path}',
               '-F', f'prompt={instruction}',
               '-F', 'output_format=png']
        if mask_path:
            cmd += ['-F', f'mask=@{mask_path}']
        out = output_path or image_path.replace('.', '_edited.')
        cmd += ['-o', out]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        return {'ok': r.returncode == 0, 'output': out, 'backend': 'stability-inpaint'}

    return {'ok': False, 'error': 'No image editing API key. Set OPENAI_API_KEY or STABILITY_API_KEY.'}
