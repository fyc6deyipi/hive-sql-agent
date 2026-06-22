"""LLM client (Node 4 emulation) calling Volcano Engine OpenAI-compatible endpoint.

Reads endpoint+key from C:/Users/Administrator/.config/opencode/opencode.jsonc
under provider "volcengine-plan". Uses model name passed in.
"""
import json
import os
import re
import time
from typing import Optional

try:
    import requests
except ImportError as e:
    raise RuntimeError("requests is required: pip install requests") from e


_CONFIG_PATH = os.path.join(os.environ.get("USERPROFILE", "C:/Users/Administrator"),
                            ".config", "opencode", "opencode.jsonc")
_CONFIG_CACHE = None


def _strip_jsonc(text: str) -> str:
    # Strip /* ... */ block comments first.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    # Strip // line comments but only when not inside a string.
    out_lines = []
    for line in text.splitlines():
        in_str = False
        escape = False
        i = 0
        cut = len(line)
        while i < len(line):
            ch = line[i]
            if escape:
                escape = False
            elif ch == "\\" and in_str:
                escape = True
            elif ch == '"':
                in_str = not in_str
            elif not in_str and ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                cut = i
                break
            i += 1
        out_lines.append(line[:cut])
    return "\n".join(out_lines)


def _load_provider():
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.loads(_strip_jsonc(f.read()))
    prov = cfg["provider"]["volcengine-plan"]
    _CONFIG_CACHE = {
        "base_url": prov["options"]["baseURL"].rstrip("/"),
        "api_key": prov["options"]["apiKey"],
        "models": list(prov.get("models", {}).keys()),
    }
    return _CONFIG_CACHE


def list_models():
    return _load_provider()["models"]


def call_llm(model: str, system_prompt: str, user_prompt: str,
             temperature: float = 0.1, max_tokens: int = 4096,
             timeout: int = 120) -> dict:
    """Call chat completion. Returns {ok, content, elapsed, usage, error}."""
    cfg = _load_provider()
    url = cfg["base_url"] + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    t0 = time.time()
    try:
        r = requests.post(url, headers=headers, json=body, timeout=timeout)
        elapsed = round(time.time() - t0, 1)
        if r.status_code != 200:
            return {
                "ok": False,
                "content": "",
                "elapsed": elapsed,
                "usage": {},
                "error": f"HTTP {r.status_code}: {r.text[:500]}",
            }
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        return {
            "ok": True,
            "content": content,
            "elapsed": elapsed,
            "usage": data.get("usage", {}),
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "content": "",
            "elapsed": round(time.time() - t0, 1),
            "usage": {},
            "error": str(e),
        }
