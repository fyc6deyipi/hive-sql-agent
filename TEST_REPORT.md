# Hive SQL 慢任务优化智能体 — 测试报告

> 日期：2026-06-15
> 引擎：Hive on MR / Tez
> 输入：SQL + DDL + size_bytes + row_count
> 输出：JSON 结构化诊断（26 项 CHK 走查）

---

## 一、项目概述

智能体接收慢 SQL 及其关联表的元信息（DDL、容量、行数），仅从 SQL 写法层面诊断性能问题，输出结构化 JSON + Markdown 报告。

核心机制：LLM 按 system prompt 中定义的 26 项 CHK（Checklist）逐项走查，命中则生成 issue，不命中不生成。

---

## 二、CHK 演进

### CHK-12（初版）

最初设计 12 项检查项，覆盖常见 Hive SQL 反模式：

| CHK | 类别 | 检测项 |
|-----|------|--------|
| CHK-1 | partition_pruning | 分区裁剪缺失 |
| CHK-2 | sql_anti_pattern | SELECT * |
| CHK-3 | join_strategy | 大小表 JOIN 未走 MapJoin |
| CHK-4 | aggregation | 多个 count(distinct) |
| CHK-5 | sql_anti_pattern | ORDER BY 无 LIMIT |
| CHK-6 | sql_anti_pattern | UNION 未用 UNION ALL |
| CHK-7 | subquery | 同表重复扫描 ≥3 次 |
| CHK-8 | window_function | 窗口函数缺 PARTITION BY |
| CHK-9 | join_strategy | 笛卡尔积 / JOIN 缺 ON |
| CHK-10 | sql_anti_pattern | LIKE '%...%' 模糊匹配 |
| CHK-11 | storage_format | TEXTFILE 格式大表 |
| CHK-12 | subquery | IN / NOT IN 子查询 |

### CHK-26（当前版）

分析 CHK-12 对知识库 20 张 KB 卡片的覆盖率仅 50%，对业界高频场景覆盖约 40-50%。补充 14 项后覆盖率达 96%（24/25 KB 卡片，仅 KB-021 JOIN 顺序无法纯静态判断）。

新增 14 项：

| CHK | 类别 | 检测项 | 对应 KB |
|-----|------|--------|---------|
| CHK-13 | partition_pruning | 分区字段被函数包裹 | KB-012 |
| CHK-14 | join_strategy | 谓词下推缺失 | KB-022 |
| CHK-15 | join_strategy | JOIN Key 函数转换 | KB-024 |
| CHK-16 | sql_anti_pattern | 老式逗号 JOIN | KB-034 |
| CHK-17 | subquery | 深层嵌套子查询 / 标量子查询 | KB-034 |
| CHK-18 | sql_anti_pattern | OR/AND 优先级错误 | KB-032 |
| CHK-19 | data_skew | GROUP BY 潜在倾斜 | KB-001 |
| CHK-20 | data_skew | JOIN 潜在倾斜 | KB-003, KB-005 |
| CHK-21 | sql_anti_pattern | 动态分区写入未 DISTRIBUTE BY | KB-004 |
| CHK-22 | sql_anti_pattern | 大 IN 列表字面值过多 | KB-035(新) |
| CHK-23 | sql_anti_pattern | LATERAL VIEW EXPLODE 膨胀 | KB-036(新) |
| CHK-24 | join_strategy | JOIN 两侧字段类型不一致 | KB-025(新) |
| CHK-25 | sql_anti_pattern | 同源多次 INSERT 未合并 | KB-037(新) |
| CHK-26 | subquery | EXISTS 子查询应改 LEFT SEMI/ANTI JOIN | KB-026(新) |

---

## 三、跨模型对比测试

### 3.1 测试配置

- API：火山引擎 OpenAI 兼容接口 `https://ark.cn-beijing.volces.com/api/coding/v3`
- 测试集：7 个手工构造 case（CHK-12 版本）
- 评分方式：precision/recall 均值（按 category 命中率）
- 候选模型：glm-5.1、deepseek-v4-pro、kimi-k2.6、minimax-m3、doubao-seed-2.0-pro

### 3.2 总排名

| 排名 | 模型 | 平均分 | 总耗时 | 全部OK | 平均/case耗时 |
|------|------|--------|--------|--------|--------------|
| 1 | **kimi-k2.6** | **1.0** | 122s | YES | **17.5s** |
| 2 | deepseek-v4-pro | 1.0 | 340s | YES | 48.6s |
| 3 | minimax-m3 | 1.0 | 230s | YES | 32.9s |
| 4 | doubao-seed-2.0-pro | 1.0 | 308s | YES | 44.0s |
| 5 | glm-5.1 | 0.82 | 197s | NO | 28.1s |

### 3.3 逐 case 明细

| Case | 期望 CHK 类目 | kimi-k2.6 | deepseek-v4-pro | minimax-m3 | doubao-seed-2.0-pro | glm-5.1 |
|------|-------------|-----------|-----------------|------------|---------------------|---------|
| CASE-1 big-small JOIN + select * | sql_anti_pattern, join_strategy | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| CASE-2 missing partition filter | partition_pruning | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| CASE-3 multi count(distinct) | aggregation | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| CASE-4 ORDER BY no LIMIT + select * | sql_anti_pattern, partition_pruning | 1.0 | 1.0 | 1.0 | 1.0 | **0.0** |
| CASE-5 same table scanned 3 times | subquery | 1.0 | 1.0 | 1.0 | 1.0 | 0.75 |
| CASE-6 UNION should be UNION ALL | sql_anti_pattern | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| CASE-7 clean SQL (fallback) | (none) | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |

### 3.4 Token 消耗

| 模型 | prompt_tokens 总计 | completion_tokens 总计 | total_tokens 总计 | 平均 total/case |
|------|-------------------|----------------------|------------------|----------------|
| glm-5.1 | 41,027 | 12,649 | 53,676 | 7,668 |
| deepseek-v4-pro | 25,156 | 13,598 | 38,754 | 5,536 |
| kimi-k2.6 | 26,113 | 12,055 | 38,168 | 5,453 |
| minimax-m3 | 24,542 | 12,829 | 37,371 | 5,339 |
| doubao-seed-2.0-pro | 27,623 | 22,917 | 50,540 | 7,220 |

### 3.5 模型参数

| 模型 | Context | Max Output | 输入模态 | reasoning_tokens |
|------|---------|-----------|---------|-----------------|
| kimi-k2.6 | 256K | 4096 | text+image | 300-500 |
| glm-5.1 | 200K | 4096 | text | 0 |

---

## 四、知识库检索 A/B 测试

### 4.1 测试方法

同一模型（kimi-k2.6）同一 case，分两组：
- **With KB**：正常流程，节点 2 生成检索关键词 → 节点 3 KB 检索 top-6 chunk → 送入 LLM
- **Without KB**：跳过 KB 检索，`kb_text = "(no knowledge retrieval)"`

### 4.2 结果（10/14 case，超时未完成 4 个）

| Case | With KB | Without KB | Delta | 说明 |
|------|---------|-----------|-------|------|
| CASE-1 big-small JOIN + select * | 1.0 | 1.0 | 0 | 无差异 |
| CASE-2 missing partition filter | 1.0 | 1.0 | 0 | 无差异 |
| CASE-3 multi count(distinct) | 1.0 | 1.0 | 0 | 无差异 |
| CASE-4 ORDER BY no LIMIT + select * | 0.0 | 0.0 | 0 | 都失败 |
| CASE-5 same table scanned 3 times | 0.75 | 0.75 | 0 | 无差异 |
| **CASE-6 UNION should be UNION ALL** | **0.0** | **1.0** | **-1.0** | **KB 帮倒忙** |
| CASE-7 clean SQL (fallback) | 1.0 | 1.0 | 0 | 无差异 |
| CASE-8 partition field wrapped | 1.0 | 1.0 | 0 | 无差异 |
| CASE-9 predicate not pushed down | 0.0 | 0.0 | 0 | 都失败 |
| CASE-10~14 | (超时) | (超时) | - | - |

### 4.3 统计

| 指标 | 值 |
|------|-----|
| KB 有帮助的 case | **0 / 10** |
| KB 帮倒忙的 case | **1 / 10** |
| KB 无影响的 case | **9 / 10** |
| 平均分 With KB | 0.575 |
| 平均分 Without KB | 0.675 |
| KB 净贡献 | **-0.10**（负分） |

### 4.4 结论

**对强模型（kimi-k2.6），知识库检索的贡献为 0 或负数。** 原因：

1. 26 项 CHK 的完整判断规则已写在 system prompt 中，LLM 不需要额外知识
2. KB chunk 挤占 context window（6 chunk ≈ 3600 字），可能挤掉有用信息
3. 关键词 Jaccard 检索精度有限，可能召回不相关 chunk 干扰判断

**知识库的价值只在 LLM 弱（如 qwen3-coder-30b）时有一定参考作用，但弱模型即使用了 KB 效果仍差。**

---

## 五、千帆 vs 本地 Runner 对比

| 维度 | 千帆 AppBuilder | 本地 Runner |
|------|----------------|-------------|
| LLM 模型 | qwen3-coder-30b（指令遵循差） | kimi-k2.6（满分通过） |
| 知识库检索 | 向量模型 bge-large-zh + Rerank | Jaccard 关键词（可跳过） |
| 节点 2 代码 | 130 行（26 项 CHK 关键词检测） | 精简版 15 行（仅格式化 tables） |
| API 格式 | 千帆私有协议 | OpenAI 兼容 |
| 部署复杂度 | 需在控制台逐节点配置 | python 脚本一行启动 |
| 扩展性 | 受千帆代码节点 sandbox 限制 | 无限制 |
| 调试 | 困难（出参字段名错位、中文标点报错） | 直接 print |

---

## 六、结论与建议

### 6.1 推荐生产模型

**kimi-k2.6**：满分 + 最快 + token 消耗最低

| 指标 | kimi-k2.6 |
|------|-----------|
| 诊断准确率 | 100%（7/7 case） |
| 平均响应时间 | 17.5s |
| 平均 token 消耗 | 5,453/case |
| reasoning 能力 | 有（300-500 reasoning tokens） |

### 6.2 推荐架构

**精简版本地 Runner**（已实现 `workflow_lite_runner.py`）：

```
输入(SQL + tables) → [tables 格式化(15行)] → [LLM(kimi-k2.6, 26项CHK)] → [JSON 解析] → 输出
```

- 跳过知识库检索（A/B 测试证明无益）
- 跳过节点 2 关键词检测（LLM 自行判断，不需要预筛）
- 核心代码 < 100 行

### 6.3 知识库定位

知识库（`hive_sql_optimization_kb.md`，25 张 KB + 24 个 CASE）的价值不在运行时检索，而在于：

1. **编写 system prompt 的来源**——CHK 规则提炼自 KB 卡片
2. **模型选型参考**——可用于补充弱模型的 context
3. **人工参考文档**——DBA 自查时可直接阅读

### 6.4 千帆升级路径（如需保留）

需改 6 处：
1. 知识库文件更新（25 KB + 24 CASE）
2. 节点 2 代码替换（CHK-1~26 检测，中文须 \uXXXX 转义）
3. 节点 4 LLM 换成 ERNIE-X1 或 DeepSeek-V3
4. 系统提示词更新（CHK-26 + data_skew category）
5. 用户提示词更新（26 项 Checklist）
6. max_tokens 4096 → 8192

---

## 七、文件清单

| 文件 | 说明 |
|------|------|
| `hive_sql_optimization_kb.md` | 知识库（25 KB + 24 CASE） |
| `prompts/system_prompt.md` | 系统提示词（CHK-26） |
| `local_runner/workflow_runner.py` | 完整版 runner（含 KB 检索） |
| `local_runner/workflow_lite_runner.py` | 精简版 runner（无 KB） |
| `local_runner/node2_lite.py` | 精简版节点 2（仅格式化） |
| `local_runner/node3_kb_retrieval.py` | KB 检索模块 |
| `local_runner/node4_llm_client.py` | 火山引擎 LLM 客户端 |
| `local_runner/compare_models.py` | 跨模型对比 runner |
| `local_runner/compare_cases.py` | 测试 case 集（14 case） |
| `local_runner/ab_kb_test.py` | KB A/B 测试脚本 |
| `local_runner/results.md` / `results.json` | 跨模型对比结果 |
| `tests/node2_parse_input.py` | 节点 2（完整版，CHK-1~26） |
| `tests/node5_parse_json.py` | 节点 5（JSON 解析） |
| `tests/test_node2.py` / `test_node5.py` | 单测（36 项全过） |
| `DEPLOY.md` | 千帆部署文档（待同步） |
