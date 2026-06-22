## POST /v1/optimize

### 请求头
```
Content-Type: application/json
Authorization: Bearer <千帆 API Key>
```

### 请求体（极简 schema）

> 千帆 AppBuilder 代码节点不支持 array/object 入参，因此 `tables` 以 **JSON 字符串** 形式传入。

```json
{
  "sql": "select a.* from dwd_order a left join dim_user b on a.user_id=b.uid where a.dt='20250101';",
  "tables": "[{\"name\":\"dwd_order\",\"ddl\":\"CREATE TABLE dwd_order (order_id string, user_id string, amount decimal(18,2)) PARTITIONED BY (dt string) STORED AS ORC;\",\"size_bytes\":536870912000,\"row_count\":5000000000},{\"name\":\"dim_user\",\"ddl\":\"CREATE TABLE dim_user (uid string, name string) STORED AS ORC;\",\"size_bytes\":52428800,\"row_count\":10000000}]"
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| sql | string | 是 | 慢任务的完整 Hive SQL |
| tables | string | 是 | 涉及表的元信息 JSON 字符串，反序列化后为数组 |

`tables` 反序列化后的每个对象包含：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 表名 |
| ddl | string | 是 | 建表语句（含分区、存储格式）|
| size_bytes | number | 是 | 表容量，字节 |
| row_count | number | 是 | 表行数 |

### 调用示例（curl）

```bash
curl -X POST https://qianfan.baidubce.com/v2/app/conversation/runs \
  -H "Authorization: Bearer $QIANFAN_API_KEY" \
  -H "Content-Type: application/json" \
  -d @examples/request_example.json
```

### 调用示例（Python）

```python
import json, requests

tables = [
    {"name": "dwd_order", "ddl": "CREATE TABLE ...", "size_bytes": 536870912000, "row_count": 5000000000},
    {"name": "dim_user",  "ddl": "CREATE TABLE ...", "size_bytes": 52428800,     "row_count": 10000000},
]

payload = {
    "sql": "select ...",
    "tables": json.dumps(tables, ensure_ascii=False),  # 关键：序列化为字符串
}

resp = requests.post(
    "https://qianfan.baidubce.com/v2/app/conversation/runs",
    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    json=payload,
)
print(resp.json())
```

### 响应体

```json
{
  "ok": true,
  "json": {
    "summary": "...",
    "severity": "high",
    "estimated_speedup": "5x",
    "issues": [
      {
        "id": "ISSUE-001",
        "category": "join_strategy",
        "severity": "high",
        "title": "...",
        "evidence": "...",
        "root_cause": "...",
        "recommendation": "...",
        "expected_gain": "3x~5x"
      }
    ],
    "needs_human_check": ["..."],
    "markdown_report": "## 总结\n..."
  },
  "markdown": "## 总结\n..."
}
```
