"""Simplified Node 2: tables formatting only (no keyword detection).

Compared to the full node2_parse_input.py (130 lines, 26 CHK detection),
this is only ~30 lines. KB retrieval has been proven unnecessary for
strong models (kimi-k2.6 etc.) - the LLM relies entirely on the 26-item
CHK checklist in the system prompt.
"""
import json


def main(params):
    sql = params.get("sql", "") or ""
    tables_raw = params.get("tables", "") or ""

    try:
        table_list = json.loads(tables_raw)
        if not isinstance(table_list, list):
            raise ValueError("tables must be a JSON array")
    except Exception as e:
        return {
            "tables_md": "[ERROR] tables parse failed: " + str(e),
            "sql": sql,
        }

    def human_size(n):
        n = float(n or 0)
        for u in ["B", "KB", "MB", "GB", "TB"]:
            if n < 1024:
                return str(round(n, 1)) + u
            n = n / 1024
        return str(round(n, 1)) + "PB"

    parts = []
    for t in table_list:
        name = t.get("name", "<unknown>")
        ddl = t.get("ddl", "")
        size = human_size(t.get("size_bytes", 0))
        rows = t.get("row_count", 0)
        parts.append(
            "## " + name + " (size=" + size + ", rows=" + str(rows) + ")\n"
            "```sql\n" + ddl + "\n```"
        )
    tables_md = "\n\n".join(parts)

    return {
        "tables_md": tables_md,
        "sql": sql,
    }
