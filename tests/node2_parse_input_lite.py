# Node 2 lite: parse input, tables formatting only (no retrieval query).
# main(params) -> dict
# Inputs (must match console "input definition"):
#   sql    : String
#   tables : String (JSON array)
# Outputs (must match console "output definition"):
#   tables_md : String  - human readable Markdown of tables
#   sql       : String  - pass-through

import json


def main(params):
    sql = params.get('sql', '') or ''
    tables_raw = params.get('tables', '') or ''

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
        for u in ['B', 'KB', 'MB', 'GB', 'TB']:
            if n < 1024:
                return str(round(n, 1)) + u
            n = n / 1024
        return str(round(n, 1)) + 'PB'

    parts = []
    for t in table_list:
        name = t.get('name', '<unknown>')
        ddl = t.get('ddl', '')
        size = human_size(t.get('size_bytes', 0))
        rows = t.get('row_count', 0)
        parts.append(
            u"## " + name + u"\uff08\u5bb9\u91cf " + size + u"\uff0c\u884c\u6570 " + str(rows) + u"\uff09\n"
            + "```sql\n" + ddl + "\n```"
        )
    tables_md = "\n\n".join(parts)

    return {
        "tables_md": tables_md,
        "sql": sql,
    }
