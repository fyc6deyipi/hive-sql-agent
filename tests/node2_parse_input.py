# Node 2: parse input + build retrieval query (Qianfan code node).
# main(params) -> dict
# Inputs (must match console "input definition"):
#   sql    : String
#   tables : String (JSON array)
# Outputs (must match console "output definition"):
#   tables_md       : String  - human readable Markdown of tables
#   retrieval_query : String  - keywords for KB retrieval
#   sql             : String  - pass-through

import json
import re


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
            "retrieval_query": sql[:500],
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

    # Build retrieval query = anti-pattern keywords detected in SQL + table flags.
    # Goal: keep query short and sharply matched against KB cards (KB-001..KB-050).
    sql_lower = sql.lower()
    keywords = []
    partition_cols = set()

    # CHK-1 partition pruning
    if "partitioned by" in " ".join([(t.get('ddl') or '').lower() for t in table_list]):
        for t in table_list:
            ddl = (t.get('ddl') or '')
            m = re.search(r"partitioned\s+by\s*\(([^)]+)\)", ddl, re.I)
            if m:
                for col in m.group(1).split(","):
                    cn = col.strip().split()[0].strip("`\"' ")
                    if cn:
                        partition_cols.add(cn.lower())
        where_part = sql_lower.split("where", 1)[1] if "where" in sql_lower else ""
        if partition_cols and not any(c in where_part for c in partition_cols):
            keywords.append(u"\u5206\u533a\u526a\u679d")  # 分区剪枝
            keywords.append("partition pruning")

    # CHK-2 SELECT *
    if re.search(r"select\s+(\*|[a-zA-Z_]\w*\.\*)", sql_lower):
        keywords.append(u"select \u661f\u53f7")  # select 星号
        keywords.append("select star column pruning")

    # CHK-3 small-large JOIN no MapJoin
    has_join = bool(re.search(r"\bjoin\b", sql_lower))
    has_mapjoin = "mapjoin" in sql_lower or "/*+" in sql_lower
    has_small_table = any((t.get('size_bytes') or 0) < 100 * 1024 * 1024 for t in table_list)
    if has_join and has_small_table and not has_mapjoin:
        keywords.append(u"\u5c0f\u8868 JOIN MapJoin")  # 小表 JOIN MapJoin
        keywords.append("MapJoin broadcast small table")

    # CHK-4 multiple count(distinct)
    distinct_cnt = len(re.findall(r"count\s*\(\s*distinct", sql_lower))
    if distinct_cnt >= 2:
        keywords.append(u"count distinct \u591a\u5b57\u6bb5")  # count distinct 多字段
        keywords.append("count distinct skew")
    elif distinct_cnt == 1 and any((t.get('size_bytes') or 0) > 10 * 1024 ** 3 for t in table_list):
        keywords.append(u"count distinct \u5927\u8868")
        keywords.append("count distinct large table")

    # CHK-5 ORDER BY no LIMIT
    if re.search(r"\border\s+by\b", sql_lower) and not re.search(r"\blimit\b", sql_lower):
        keywords.append(u"order by \u5168\u5c40\u6392\u5e8f \u65e0 limit")
        keywords.append("order by no limit global sort")

    # CHK-6 UNION (not UNION ALL)
    if re.search(r"\bunion\b(?!\s+all)", sql_lower):
        keywords.append(u"UNION \u9690\u5f0f\u53bb\u91cd")  # UNION 隐式去重
        keywords.append("UNION ALL deduplicate")

    # CHK-7 same table scanned >= 3 times
    table_refs = {}
    for t in table_list:
        n = (t.get('name') or '').lower()
        if n:
            table_refs[n] = len(re.findall(r"\b" + re.escape(n) + r"\b", sql_lower))
    if any(c >= 3 for c in table_refs.values()):
        keywords.append(u"\u540c\u8868\u91cd\u590d\u626b\u63cf")  # 同表重复扫描
        keywords.append("repeated table scan grouping sets")

    # CHK-8 window function over()
    if "over(" in sql_lower or "over (" in sql_lower:
        m = re.search(r"over\s*\(\s*([^)]*)\)", sql_lower)
        if m and "partition by" not in m.group(1):
            keywords.append(u"\u7a97\u53e3\u51fd\u6570 partition by")
            keywords.append("window function partition by")

    # CHK-9 cross join / cartesian
    if "cross join" in sql_lower:
        keywords.append(u"\u7b1b\u5361\u5c14\u79ef")  # 笛卡尔积
        keywords.append("cartesian product cross join")

    # CHK-10 LIKE %xxx% on big table
    if re.search(r"like\s+'%[^']+%'", sql_lower):
        keywords.append("LIKE \u6a21\u7cca\u5339\u914d")
        keywords.append("LIKE wildcard full scan")

    # CHK-11 storage format
    for t in table_list:
        ddl_l = (t.get('ddl') or '').lower()
        if "stored as textfile" in ddl_l and (t.get('size_bytes') or 0) > 10 * 1024 ** 3:
            keywords.append(u"\u5b58\u50a8\u683c\u5f0f TEXTFILE ORC")
            keywords.append("storage format ORC parquet")
            break

    # CHK-12 IN (SELECT ...) / NOT IN
    if re.search(r"\bin\s*\(\s*select\b", sql_lower) or re.search(r"\bnot\s+in\s*\(\s*select\b", sql_lower):
        keywords.append(u"IN \u5b50\u67e5\u8be2 LEFT SEMI JOIN")
        keywords.append("IN subquery LEFT SEMI JOIN")

    # CHK-13 partition field wrapped by function
    if partition_cols:
        where_part_full = sql_lower.split("where", 1)[1] if "where" in sql_lower else ""
        for pc in partition_cols:
            func_patterns = [
                r"substr\s*\(\s*" + re.escape(pc) + r"\s*,",
                r"substring\s*\(\s*" + re.escape(pc) + r"\s*,",
                r"year\s*\(\s*" + re.escape(pc) + r"\s*\)",
                r"month\s*\(\s*" + re.escape(pc) + r"\s*\)",
                r"day\s*\(\s*" + re.escape(pc) + r"\s*\)",
                r"to_date\s*\(\s*" + re.escape(pc) + r"\s*[\),]",
                r"cast\s*\(\s*" + re.escape(pc) + r"\s+as\s+",
                r"concat\s*\(\s*" + re.escape(pc) + r"\s*,",
                r"date_format\s*\(\s*" + re.escape(pc) + r"\s*,",
            ]
            for pat in func_patterns:
                if re.search(pat, sql_lower):
                    keywords.append(u"\u5206\u533a\u5b57\u6bb5\u51fd\u6570\u5305\u88f9")
                    keywords.append("partition field function wrap pruning失效")
                    break

    # CHK-14 predicate not pushed down
    if has_join and "where" in sql_lower:
        outer_aliases = set()
        for t in table_list:
            n = (t.get('name') or '').lower()
            if n:
                alias_m = re.search(re.escape(n) + r"\s+([a-zA-Z_]\w*)", sql_lower)
                if alias_m:
                    outer_aliases.add(alias_m.group(1).lower())
        simple_filters = re.findall(
            r"where\s+.+$", sql_lower, re.M | re.S
        )
        if simple_filters:
            for al in outer_aliases:
                if re.search(re.escape(al) + r"\.\w+\s*(=|!=|<>|>|<|>=|<=|like|in)\s", simple_filters[0]):
                    keywords.append(u"\u8c13\u8bcd\u4e0b\u63a8\u7f3a\u5931")
                    keywords.append("predicate pushdown filter subquery")
                    break

    # CHK-15 JOIN Key function conversion
    if has_join:
        on_matches = re.findall(r"\bon\s+(.+?)(?:\b(left|right|inner|outer|cross|full|join)\b|$)", sql_lower)
        for on_clause, _ in on_matches:
            if re.search(r"(lower|upper|trim|substr|substring|cast|concat)\s*\(", on_clause):
                keywords.append(u"JOIN Key \u51fd\u6570\u8f6c\u6362")
                keywords.append("JOIN key function conversion")
                break

    # CHK-16 comma JOIN (old-style)
    from_match = re.search(r"\bfrom\s+(.+?)(?:\bwhere\b)", sql_lower, re.S)
    if from_match:
        from_clause = from_match.group(1)
        if re.search(r"\b\w+\s*,\s*\w+", from_clause):
            keywords.append(u"\u8001\u5f0f\u9017\u53f7 JOIN")
            keywords.append("comma join old style")

    # CHK-17 deep nested subquery / scalar subquery
    subq_depth = sql_lower.count("(select")
    if subq_depth >= 3:
        keywords.append(u"\u6df1\u5c42\u5d4c\u5957\u5b50\u67e5\u8be2")
        keywords.append("deep nested subquery CTE")
    if re.search(r"select\s+\(\s*select\b", sql_lower):
        keywords.append(u"\u6807\u91cf\u5b50\u67e5\u8be2")
        keywords.append("scalar subquery LEFT JOIN")

    # CHK-18 OR/AND precedence
    if re.search(r"\band\b", sql_lower) and re.search(r"\bor\b", sql_lower):
        or_parts = sql_lower.split(" or ")
        needs_check = False
        for p in or_parts[:-1]:
            if "(" not in p.split(" or ")[-1] if " or " in p else p:
                if not re.search(r"\(\s*.*\bor\b.*\s*\)", p):
                    needs_check = True
                    break
        if needs_check or not re.search(r"\(.*\bor\b.*\)", sql_lower):
            keywords.append(u"OR AND \u4f18\u5148\u7ea7")
            keywords.append("OR AND precedence bracket")

    # CHK-19 GROUP BY potential skew
    if re.search(r"\bgroup\s+by\b", sql_lower):
        if any((t.get('size_bytes') or 0) > 10 * 1024 ** 3 or (t.get('row_count') or 0) > 100_000_000
               for t in table_list):
            keywords.append(u"GROUP BY \u6f5c\u5728\u503e\u659c")
            keywords.append("GROUP BY skew risk data distribution")

    # CHK-20 JOIN potential skew (both sides large)
    if has_join:
        large_tables = [t for t in table_list if (t.get('size_bytes') or 0) > 10 * 1024 ** 3]
        if len(large_tables) >= 2:
            keywords.append(u"JOIN \u6f5c\u5728\u503e\u659c")
            keywords.append("JOIN skew risk NULL distribution")

    # CHK-21 dynamic partition without DISTRIBUTE BY
    if re.search(r"insert\s+overwrite\s+table\s+\w+\s+partition\s*\(\s*\w+\s*\)", sql_lower):
        if "distribute by" not in sql_lower:
            keywords.append(u"\u52a8\u6001\u5206\u533a DISTRIBUTE BY")
            keywords.append("dynamic partition distribute by small files")

    # CHK-22 large IN list (>100 literals)
    in_literal_matches = re.findall(r"\bin\s*\(([^()]+)\)", sql_lower)
    for m in in_literal_matches:
        if "select" not in m:
            literal_count = len([v for v in m.split(",") if v.strip()])
            if literal_count > 100:
                keywords.append(u"\u5927 IN \u5217\u8868")
                keywords.append("large IN list JOIN instead")
                break

    # CHK-23 LATERAL VIEW EXPLODE on big table
    if re.search(r"\blateral\s+view\s+(outer\s+)?explode\b", sql_lower):
        if any((t.get('size_bytes') or 0) > 10 * 1024 ** 3 or (t.get('row_count') or 0) > 100_000_000
               for t in table_list):
            keywords.append(u"LATERAL VIEW EXPLODE \u81a8\u80c0")
            keywords.append("LATERAL VIEW EXPLODE row expansion")

    # CHK-24 JOIN type mismatch
    if has_join and len(table_list) >= 2:
        col_types = {}
        for t in table_list:
            ddl = (t.get('ddl') or '')
            for cm in re.finditer(r"(\w+)\s+(string|bigint|int|decimal|double|float|date|timestamp)", ddl, re.I):
                cn = cm.group(1).lower()
                ct = cm.group(2).lower()
                if cn not in col_types:
                    col_types[cn] = ct
                elif col_types[cn] != ct:
                    keywords.append(u"JOIN \u7c7b\u578b\u4e0d\u4e00\u81f4")
                    keywords.append("JOIN type mismatch implicit conversion")
                    break
            else:
                continue
            break

    # CHK-25 multi INSERT same source
    insert_count = len(re.findall(r"\binsert\s+(into|overwrite)\b", sql_lower))
    if insert_count >= 2:
        from_tables_in_inserts = []
        for im in re.finditer(r"\binsert\s+(?:into|overwrite)\b.+?\bfrom\s+(\w+)", sql_lower, re.S):
            from_tables_in_inserts.append(im.group(1).lower())
        if len(from_tables_in_inserts) >= 2:
            first = from_tables_in_inserts[0]
            if all(t == first for t in from_tables_in_inserts):
                keywords.append(u"\u540c\u6e90\u591a\u6b21 INSERT")
                keywords.append("multi insert same source")

    # CHK-26 EXISTS / NOT EXISTS subquery
    if re.search(r"\bexists\s*\(\s*select\b", sql_lower) or re.search(r"\bnot\s+exists\s*\(\s*select\b", sql_lower):
        keywords.append(u"EXISTS \u5b50\u67e5\u8be2")
        keywords.append("EXISTS subquery LEFT SEMI JOIN")

    # Fallback: if nothing detected, fall back to short SQL summary
    if not keywords:
        keywords.append("Hive SQL optimization")
        # take first 200 chars of SQL as fallback signal
        keywords.append(sql[:200])

    retrieval_query = " ; ".join(keywords)
    if len(retrieval_query) > 500:
        retrieval_query = retrieval_query[:500]

    return {
        "tables_md": tables_md,
        "retrieval_query": retrieval_query,
        "sql": sql,
    }
