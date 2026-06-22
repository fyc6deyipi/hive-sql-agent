"""Local end-to-end workflow runner.

Pipeline (mirrors the Qianfan workflow exactly):
  1. start node: receive sql + tables (list of dicts)
  2. node 2 (param parsing): tests/node2_parse_input.main
  3. node 3 (KB retrieval): local_runner/node3_kb_retrieval.retrieve
  4. node 4 (LLM): local_runner/node4_llm_client.call_llm
  5. node 5 (JSON parsing): tests/node5_parse_json.main
  6. end node: returns {ok, json, markdown}

Usage:
  from local_runner.workflow_runner import run
  result = run(sql, tables, model="glm-5.1")
"""
import json
import os
import sys

_HERE = os.path.dirname(__file__)
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "tests"))
sys.path.insert(0, _HERE)

from node2_parse_input import main as node2_main
from node5_parse_json import main as node5_main

import node3_kb_retrieval as kb
import node4_llm_client as llm


def _load_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


_SYSTEM_PROMPT = _load_text(os.path.join(_ROOT, "prompts", "system_prompt.md"))


def _build_user_prompt(sql: str, tables_md: str, kb_text: str) -> str:
    return (
        "<input>\n"
        "sql:\n" + sql + "\n\n"
        "tables:\n" + tables_md + "\n"
        "</input>\n\n"
        "按系统提示词中的 26 项 Checklist 逐项走查，命中的生成 issue，不命中的跳过。"
        " 仅输出 JSON，不要 ``` 包裹，不要 Markdown 标题前缀。"
    )


def run(sql: str, tables: list, model: str = "glm-5.1",
        temperature: float = 0.1, max_tokens: int = 8192) -> dict:
    """Run full workflow. Returns dict with all intermediate stages for inspection."""
    # Node 1: start (input pass-through). Tables must be passed as JSON string into node 2.
    tables_json_str = json.dumps(tables, ensure_ascii=False)

    # Node 2: parameter parsing.
    n2 = node2_main({"sql": sql, "tables": tables_json_str})

    # Node 3: KB retrieval (local).
    chunks = kb.retrieve(n2["retrieval_query"], top_k=6)
    kb_text = kb.format_chunks(chunks)

    # Node 4: LLM call.
    user_prompt = _build_user_prompt(n2["sql"], n2["tables_md"], kb_text)
    llm_resp = llm.call_llm(model, _SYSTEM_PROMPT, user_prompt,
                            temperature=temperature, max_tokens=max_tokens)

    # Node 5: JSON parsing.
    if not llm_resp["ok"]:
        n5 = {"ok": False, "json": {"error": llm_resp["error"], "raw": ""},
              "markdown": "## LLM 调用失败\n\n" + (llm_resp["error"] or "")}
    else:
        n5 = node5_main({"output": llm_resp["content"]})

    return {
        "model": model,
        "stages": {
            "node2_retrieval_query": n2["retrieval_query"],
            "node3_chunk_count": len(chunks),
            "node3_chunk_titles": [c["title"] for c in chunks],
            "node4_elapsed_s": llm_resp["elapsed"],
            "node4_usage": llm_resp["usage"],
            "node4_raw_content": llm_resp["content"][:300],
        },
        "ok": n5["ok"],
        "json": n5["json"],
        "markdown": n5["markdown"],
        "error": llm_resp.get("error"),
    }
