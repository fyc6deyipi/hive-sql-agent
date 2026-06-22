# 千帆 AppBuilder 部署指南

## 一、平台准备
1. 登录 [千帆 AppBuilder](https://console.bce.baidu.com/qianfan/appbuilder)
2. 创建应用：选择「**工作流 Agent**」类型（非「自主规划 Agent」，因为我们流程固定）
3. 模型：在工作流的 LLM 节点选择 **qwen-code**（如平台命名为 Qwen2.5-Coder / Qwen3-Coder 同选编码版）

## 二、知识库
1. 进入「知识库」→「新建」→ 命名 `hive_optimization_kb`
2. **整目录上传** `knowledge/` 下所有 `.md` 文件（30 张 KB + CASE 卡片）
3. 切片配置：
   - 切片方式：**按文件切片**（每张卡 = 1 chunk，ID 体系便于精准召回）
   - 若平台只支持按标题切片：选择 `##` 二级标题切分，长度 600~1000 token，重叠 100
4. 向量化模型：默认 bge-large-zh / Embedding-V1
5. 可选元数据维度：从卡片头部解析 `分类`、`严重度`，作为过滤字段
6. 等待索引构建完成
7. 调试召回：用关键词测试，如"分区裁剪 + JOIN"应能召回 KB-011 / KB-022 / KB-024

## 三、工作流节点

```
[开始] → [参数解析] → [知识库检索] → [LLM 调用] → [JSON 解析] → [结束]
```

### 节点 1：开始（输入参数）
> ⚠️ 千帆 AppBuilder 代码节点入参仅支持 String / Number / Boolean / Any 四种类型，不支持 Array / Object。
> 因此 `tables` 必须以 **JSON 字符串** 形式传入，由代码节点内部反序列化。

配置以下入参（对应 `schema/api_schema.md`）：
| 变量名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| sql | String | 是 | 慢任务 SQL |
| tables | String | 是 | tables 数组的 JSON 字符串形式 |

### 节点 2：参数解析（代码节点，Python）

> ⚠️ 千帆代码节点函数签名固定为 `def main(params):`，所有入参通过 `params['变量名']` 访问。

作用：反序列化 tables 字符串，把它渲染成 Markdown 文本，并合并出检索 query。

```python
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

    # Build retrieval_query as anti-pattern keywords detected statically from SQL + tables.
    sql_lower = sql.lower()
    keywords = []

    # CHK-1 partition pruning
    if "partitioned by" in " ".join([(t.get('ddl') or '').lower() for t in table_list]):
        partition_cols = set()
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
            keywords.append(u"\u5206\u533a\u526a\u679d")
            keywords.append("partition pruning")

    # CHK-2 SELECT *
    if re.search(r"select\s+(\*|[a-zA-Z_]\w*\.\*)", sql_lower):
        keywords.append(u"select \u661f\u53f7")
        keywords.append("select star column pruning")

    # CHK-3 small-large JOIN no MapJoin
    has_join = bool(re.search(r"\bjoin\b", sql_lower))
    has_mapjoin = "mapjoin" in sql_lower or "/*+" in sql_lower
    has_small_table = any((t.get('size_bytes') or 0) < 100 * 1024 * 1024 for t in table_list)
    if has_join and has_small_table and not has_mapjoin:
        keywords.append(u"\u5c0f\u8868 JOIN MapJoin")
        keywords.append("MapJoin broadcast small table")

    # CHK-4 multiple count(distinct)
    distinct_cnt = len(re.findall(r"count\s*\(\s*distinct", sql_lower))
    if distinct_cnt >= 2:
        keywords.append(u"count distinct \u591a\u5b57\u6bb5")
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
        keywords.append(u"UNION \u9690\u5f0f\u53bb\u91cd")
        keywords.append("UNION ALL deduplicate")

    # CHK-7 same table referenced 3+ times
    table_refs = {}
    for t in table_list:
        n = (t.get('name') or '').lower()
        if n:
            table_refs[n] = len(re.findall(r"\b" + re.escape(n) + r"\b", sql_lower))
    if any(c >= 3 for c in table_refs.values()):
        keywords.append(u"\u540c\u8868\u91cd\u590d\u626b\u63cf")
        keywords.append("repeated table scan grouping sets")

    # CHK-8 window function over() without partition by
    if "over(" in sql_lower or "over (" in sql_lower:
        m = re.search(r"over\s*\(\s*([^)]*)\)", sql_lower)
        if m and "partition by" not in m.group(1):
            keywords.append(u"\u7a97\u53e3\u51fd\u6570 partition by")
            keywords.append("window function partition by")

    # CHK-9 cross join
    if "cross join" in sql_lower:
        keywords.append(u"\u7b1b\u5361\u5c14\u79ef")
        keywords.append("cartesian product cross join")

    # CHK-10 LIKE wildcard
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

    # CHK-12 IN (SELECT ...)
    if re.search(r"\bin\s*\(\s*select\b", sql_lower) or re.search(r"\bnot\s+in\s*\(\s*select\b", sql_lower):
        keywords.append(u"IN \u5b50\u67e5\u8be2 LEFT SEMI JOIN")
        keywords.append("IN subquery LEFT SEMI JOIN")

    if not keywords:
        keywords.append("Hive SQL optimization")
        keywords.append(sql[:200])

    retrieval_query = " ; ".join(keywords)
    if len(retrieval_query) > 500:
        retrieval_query = retrieval_query[:500]

    return {
        "tables_md": tables_md,
        "retrieval_query": retrieval_query,
        "sql": sql,
    }
```

**节点 2 出参类型配置**：
| 变量名 | 类型 |
|--------|------|
| tables_md | String |
| retrieval_query | String |
| sql | String |

### 节点 3：知识库检索
- 知识库：`hive_optimization_kb`
- Query：`{{节点2.retrieval_query}}`
- Top-K：5
- 输出变量：`retrieved_chunks`

### 节点 4：LLM 调用（核心）
- 模型：**qwen-code**
- 温度：0.1（要稳定，不要发挥）
- max_tokens：4096（无需改写 SQL，输出更紧凑）
- 响应格式：**JSON Mode**（千帆若支持则开启；否则在 prompt 末尾强调）

**系统提示词**：直接粘贴 `prompts/system_prompt.md` 全文。

**用户提示词**（粘贴并替换变量为千帆变量语法 `{{变量}}`）：
```
请基于下面提供的 Hive 慢任务信息，按系统指令进行 SQL 写法层面的诊断，输出严格符合 schema 的 JSON。
注意：不要返回 set 参数、不要返回改写后的 SQL、不要猜测数据分布。

<input>
# 慢 SQL
```sql
{{节点1.sql}}
```

# 涉及表（DDL + 容量 + 行数）
{{节点2.tables_md}}
</input>

<knowledge>
{{节点3.retrieved_chunks}}
</knowledge>

请输出 JSON。
```

### 节点 5：JSON 解析（代码节点）

> 入参 `output` 由节点 4 输出，类型为 String。
> 函数签名固定为 `def main(params):`（千帆要求）。
> `json` 出参类型用 **Any**（控制台支持的 dict）；如必须用 String，本节点也会输出可 JSON.parse 的 dict，请在控制台改成 String 时手动 json.dumps。

```python
"""Node 5: JSON parsing (Qianfan code node - Python).

Qianfan requires the function signature to be `def main(params):`,
all inputs are passed via the `params` dict.

Inputs (must match console "input definition" exactly):
  output : String - raw output of LLM node 4

Outputs (must match console "output definition" exactly, case sensitive):
  ok       : Boolean
  json     : Any      - parsed structured result (dict)
  markdown : String   - human-readable Markdown report
"""
import json
import re


def _try_parse_json(txt):
    if not txt:
        return None
    candidates = [txt.strip()]
    m = re.search(r"```json\s*(.+?)\s*```", txt, re.S)
    if m:
        candidates.append(m.group(1).strip())
    m = re.search(r"```\s*(\{.+?\})\s*```", txt, re.S)
    if m:
        candidates.append(m.group(1).strip())
    if "{" in txt and "}" in txt:
        candidates.append(txt[txt.find("{"): txt.rfind("}") + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return None


def _markdown_from_json(data):
    md = data.get("markdown_report") or data.get("markdown") or data.get("markdown_output")
    if md:
        return md

    parts = []
    if data.get("summary"):
        parts.append(u"## \u603b\u7ed3\n\n" + str(data["summary"]))
    if data.get("severity"):
        parts.append(u"**\u4e25\u91cd\u7b49\u7ea7**\uff1a" + str(data["severity"]))
    if data.get("estimated_speedup"):
        parts.append(u"**\u9884\u4f30\u6536\u76ca**\uff1a" + str(data["estimated_speedup"]))

    issues = data.get("issues") or []
    if issues:
        parts.append(u"## \u95ee\u9898\u5217\u8868")
        for i, iss in enumerate(issues, 1):
            parts.append(
                u"### " + str(iss.get("id", "ISSUE-" + str(i).zfill(3)))
                + u" [" + str(iss.get("severity", "")) + u"] "
                + str(iss.get("category", "")) + u": "
                + str(iss.get("title", "")) + u"\n"
                + u"- **\u8bc1\u636e**\uff1a" + str(iss.get("evidence", "")) + u"\n"
                + u"- **\u6839\u56e0**\uff1a" + str(iss.get("root_cause", "")) + u"\n"
                + u"- **\u5efa\u8bae**\uff1a" + str(iss.get("recommendation", "")) + u"\n"
                + u"- **\u9884\u4f30\u6536\u76ca**\uff1a" + str(iss.get("expected_gain", ""))
            )

    needs = data.get("needs_human_check") or []
    if needs:
        parts.append(u"## \u9700\u4eba\u5de5\u6838\u67e5\u9879")
        for n in needs:
            parts.append(u"- " + str(n))

    return "\n\n".join(parts) if parts else ""


def main(params):
    raw = params.get("output", "") or ""
    txt = str(raw).strip()

    if txt.startswith("output{") or txt.startswith("output {"):
        txt = txt[len("output"):].lstrip()

    data = _try_parse_json(txt)

    if isinstance(data, dict):
        return {
            "ok": True,
            "json": data,
            "markdown": _markdown_from_json(data),
        }

    looks_like_md = txt.startswith("#") or "\n## " in txt or "\n### " in txt
    if looks_like_md:
        return {
            "ok": True,
            "json": {
                "summary": "",
                "severity": "",
                "estimated_speedup": "",
                "issues": [],
                "needs_human_check": [],
                "markdown_report": txt,
                "_warning": "LLM did not output JSON per schema, passed through as Markdown",
            },
            "markdown": txt,
        }

    return {
        "ok": False,
        "json": {
            "error": "JSON parse failed and not markdown",
            "raw": txt[:2000],
        },
        "markdown": u"## JSON \u89e3\u6790\u5931\u8d25\n\n```\n" + txt[:2000] + u"\n```",
    }
```

**节点 5 入参定义**：
| 变量名 | 类型 | 引用 |
|--------|------|------|
| output | String | {{节点4.output}} |

**节点 5 出参定义**（名字必须严格一致）：
| 变量名 | 类型 | 说明 |
|--------|------|------|
| ok | Boolean | 解析是否成功 |
| json | Any | 结构化结果（dict） |
| markdown | String | 人读 Markdown 报告 |

### 节点 6：结束
出参：
| 名称 | 来源 |
|------|------|
| ok | {{节点5.ok}} |
| json | {{节点5.json}} |
| markdown | {{节点5.markdown}} |

## 四、发布为 API
1. 工作流调试通过后，点「发布」
2. 在「服务管理」中获取：
   - Endpoint：`https://qianfan.baidubce.com/v2/app/conversation/runs`（具体看千帆文档）
   - App ID、API Key
3. 调用示例（curl）：
```bash
curl -X POST https://qianfan.baidubce.com/v2/app/conversation/runs \
  -H "Authorization: Bearer $QIANFAN_API_KEY" \
  -H "Content-Type: application/json" \
  -d @examples/request_example.json
```

## 五、调优清单（上线后）
1. **稳定性**：若 JSON 解析失败率 > 5%，把 temperature 降到 0，并在系统 prompt 加 1~2 个 few-shot 示例。
2. **召回质量**：调试期打印 `retrieved_chunks`，若总是召回不到关键规则，把 retrieval_query 改成"问题分类关键词"（先用一个小 LLM 节点提炼）。
3. **成本**：DDL 很长时（超 4KB）做截断，只保留分区/分桶/存储格式相关 DDL 行。
4. **A/B**：保留 model 节点为变量，可一键切到 qwen 通用版做对比。
5. **回归集**：积累 20 个典型慢 SQL + 期望诊断，每次 prompt 变更跑一次。
