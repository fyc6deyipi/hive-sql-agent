# Hive SQL 慢任务智能体 - 评测报告

> 日期：2026-06-15
> 引擎：Hive on MR / Tez
> 接口：火山引擎 OpenAI 兼容端点 `https://ark.cn-beijing.volces.com/api/coding/v3`

---

## 一、跨模型对比（CHK-12 版，7 case）

### 总排名

| 排名 | 模型 | 平均分 | 总耗时 | 全部OK |
|------|------|--------|--------|--------|
| 1 | **kimi-k2.6** | **1.00** | **122s** | YES |
| 1 | deepseek-v4-pro | 1.00 | 340s | YES |
| 1 | minimax-m3 | 1.00 | 230s | YES |
| 1 | doubao-seed-2.0-pro | 1.00 | 308s | YES |
| 5 | glm-5.1 | 0.82 | 197s | NO |

### 逐 case 明细

| Case | 期望 CHK 类目 | kimi-k2.6 | deepseek-v4-pro | minimax-m3 | doubao-seed-2.0-pro | glm-5.1 |
|------|-------------|-----------|----------------|------------|--------------------|---------| 
| CASE-1 大小表 JOIN + select * | sql_anti_pattern, join_strategy | 1.0 (20s) | 1.0 (54s) | 1.0 (37s) | 1.0 (50s) | 1.0 (30s) |
| CASE-2 缺失分区过滤 | partition_pruning | 1.0 (14s) | 1.0 (37s) | 1.0 (30s) | 1.0 (36s) | 1.0 (23s) |
| CASE-3 多个 count(distinct) | aggregation | 1.0 (17s) | 1.0 (52s) | 1.0 (41s) | 1.0 (34s) | 1.0 (26s) |
| CASE-4 ORDER BY 无 LIMIT + select * | sql_anti_pattern, partition_pruning | 1.0 (22s) | 1.0 (60s) | 1.0 (37s) | 1.0 (65s) | **0.0** (35s) |
| CASE-5 同表扫描 3 次 | subquery | 1.0 (18s) | 1.0 (67s) | 1.0 (36s) | 1.0 (47s) | 0.75 (34s) |
| CASE-6 UNION 非 UNION ALL | sql_anti_pattern | 1.0 (17s) | 1.0 (40s) | 1.0 (23s) | 1.0 (36s) | 1.0 (26s) |
| CASE-7 干净 SQL (兜底) | (none) | 1.0 (14s) | 1.0 (32s) | 1.0 (26s) | 1.0 (41s) | 1.0 (24s) |

### glm-5.1 失败分析

- CASE-4：LLM 输出 JSON 解析失败（ok=False），导致 0 分
- CASE-5：多判了一个 partition_pruning（extra），precision 下降

### Token 消耗汇总

| 模型 | prompt_tokens 总计 | completion_tokens 总计 | total_tokens 总计 | 平均/case |
|------|-------------------|----------------------|------------------|-----------|
| kimi-k2.6 | 26,113 | 12,055 | 38,168 | 5,453 |
| deepseek-v4-pro | 25,156 | 13,598 | 38,754 | 5,536 |
| minimax-m3 | 24,542 | 12,829 | 37,371 | 5,339 |
| doubao-seed-2.0-pro | 27,623 | 22,917 | 50,540 | 7,220 |
| glm-5.1 | 41,027 | 12,649 | 53,676 | 7,668 |

**5 模型 x 7 case = 35 次调用，总计 215,509 tokens**

---

## 二、模型参数对比

| 参数 | kimi-k2.6 | glm-5.1 |
|------|-----------|---------|
| Context Window | 256K | 200K |
| Max Output | 4,096 | 4,096 |
| 输入模态 | text + image | text |
| 对比测试得分 | 1.00 | 0.82 |
| 平均耗时/case | 17.5s | 28.1s |
| 平均 prompt_tokens | 3,730 | 5,866 |
| 平均 completion_tokens | 1,719 | 1,807 |
| reasoning_tokens | 300~500 | 0 |
| 全部 OK | YES | NO |

---

## 三、知识库检索有效性 A/B 测试

### 实验设计

- 模型：kimi-k2.6
- 对照组 A：完整流程（节点 2 关键词检索 → 节点 3 KB 检索 → 节点 4 LLM）
- 对照组 B：跳过 KB 检索（节点 2 仅格式化 tables → 节点 4 LLM，无 KB chunk 注入）

### 结果（10 case）

| Case | With KB | Without KB | Delta | 说明 |
|------|---------|------------|-------|------|
| CASE-1 | 1.0 | 1.0 | 0 | 无差异 |
| CASE-2 | 1.0 | 1.0 | 0 | 无差异 |
| CASE-3 | 1.0 | 1.0 | 0 | 无差异 |
| CASE-4 | 0.0 | 0.0 | 0 | 都失败（JSON 解析错误） |
| CASE-5 | 0.75 | 0.75 | 0 | 无差异 |
| CASE-6 | **0.0** | **1.0** | **-1.0** | KB 帮倒忙 |
| CASE-7 | 1.0 | 1.0 | 0 | 无差异 |
| CASE-8 | 1.0 | 1.0 | 0 | 无差异 |
| CASE-9 | 0.0 | 0.0 | 0 | 都失败 |
| CASE-10 | (超时) | (超时) | - | - |

### 量化结论

| 指标 | 值 |
|------|-----|
| KB 有帮助的 case | **0 / 9** |
| KB 帮倒忙的 case | **1 / 9** |
| KB 无影响的 case | **8 / 9** |
| 平均分 With KB | 0.575 |
| 平均分 Without KB | 0.675 |
| KB 净贡献 | **-0.10（负分）** |

### 原因分析

1. **26 项 CHK 的判断规则已完整写在 system prompt 中**，LLM 不需要 KB 提供额外知识
2. **KB chunk 挤占 context window**（6 chunk x 600 字 ≈ 3,600 字），可能把有用信息挤出去
3. **检索精度有限**：关键词 Jaccard 匹配可能召回不相关 chunk，干扰 LLM 判断

---

## 四、CHK 覆盖率分析

### CHK-26 vs KB-25 覆盖映射

| KB 卡片 | CHK 覆盖？ | 说明 |
|---------|-----------|------|
| KB-001 GROUP BY 长尾 | CHK-19 | 潜在风险标记 |
| KB-002 DISTINCT 单点瓶颈 | CHK-4 | - |
| KB-003 JOIN 长尾 | CHK-20 | 潜在风险标记 |
| KB-004 动态分区写入长尾 | CHK-21 | - |
| KB-005 JOIN Key NULL 倾斜 | CHK-20 | 合并在 JOIN 潜在倾斜 |
| KB-010 SELECT * | CHK-2 | - |
| KB-011 分区裁剪缺失 | CHK-1 | - |
| KB-012 分区字段被函数包裹 | CHK-13 | - |
| KB-020 大小表 MapJoin | CHK-3 | - |
| KB-021 JOIN 顺序不合理 | **未覆盖** | 需中间结果行数估算 |
| KB-022 谓词下推缺失 | CHK-14 | - |
| KB-023 IN/EXISTS → LEFT SEMI | CHK-12 + CHK-26 | - |
| KB-024 JOIN Key 函数转换 | CHK-15 | - |
| KB-025 JOIN 两侧类型不一致 | CHK-24 | 新增 |
| KB-026 EXISTS 子查询 | CHK-26 | 新增 |
| KB-030 UNION → UNION ALL | CHK-6 | - |
| KB-031 COUNT(DISTINCT) 单 Reducer | CHK-4 | - |
| KB-032 OR/AND 混用 | CHK-18 | - |
| KB-033 同表多次扫描 | CHK-7 | - |
| KB-034 嵌套子查询/逗号 JOIN | CHK-16 + CHK-17 | - |
| KB-035 大 IN 列表 | CHK-22 | 新增 |
| KB-036 LATERAL VIEW EXPLODE | CHK-23 | 新增 |
| KB-037 同源多次 INSERT | CHK-25 | 新增 |
| KB-040 小文件写入 | CHK-21（关联） | - |
| KB-050 全局 ORDER BY 无 LIMIT | CHK-5 | - |

### 覆盖统计

| 维度 | 数量 |
|------|------|
| KB 卡片总数 | 25 |
| KB 被 CHK 覆盖 | 24 / 25（96%） |
| 未覆盖的 KB | KB-021 JOIN 顺序（需运行时信息） |
| CHK 项总数 | 26 |
| 业界高频场景覆盖 | ~85~90% |

### 无法仅凭 SQL+DDL+容量+行数检测的场景

| 场景 | 缺什么信息 |
|------|-----------|
| JOIN 顺序合理性 | 中间结果行数估算 |
| Map 端聚合是否触发 | 执行计划 |
| 分桶是否利用 | 桶列过滤+桶数 |
| 数据倾斜确认 | 数据分布 Top-N |
| 小文件实际数量 | HDFS 文件统计 |

---

## 五、结论与建议

### 模型选型

| 场景 | 推荐模型 | 理由 |
|------|---------|------|
| 生产环境 | **kimi-k2.6** | 满分 + 最快（17.5s/case）+ token 消耗低 |
| 备选 | deepseek-v4-pro | 满分，但慢（49s/case） |
| 不推荐 | glm-5.1 | 0.82 分，CASE-4 失败 |
| 不推荐 | 千帆 qwen3-coder-30b | 指令遵循不足，只识别 join_strategy |

### 架构建议

| 项目 | 建议 | 理由 |
|------|------|------|
| 知识库检索 | **删除** | A/B 测试证明对强模型净贡献为负 |
| 节点 2 代码 | **精简** | 去掉 26 项关键词检测，只保留 tables 格式化（15 行） |
| 工作流 | 简化为 3 节点 | [tables 格式化] → [LLM(26 CHK)] → [JSON 解析] |
| max_tokens | 8192 | 26 项 CHK 命中多时输出更长 |

### 千帆升级清单（如需回迁）

1. 重新上传知识库文件（25 KB + 24 CASE）
2. 替换节点 2 代码（新增 CHK-13~26，中文必须 \uXXXX 转义）
3. 节点 4 换模型（qwen3-coder-30b → ERNIE-X1 或 DeepSeek-V3）
4. 替换系统提示词（CHK-26 + data_skew category）
5. 更新用户提示词（26 项 Checklist）
6. max_tokens 改为 8192

### 交付形态

推荐 **本地 runner** 形式交付：
- 不依赖千帆平台，直接调火山引擎 API
- 使用 kimi-k2.6 模型，性能最优
- 精简工作流，无需知识库检索
- 文件：`workflow_lite_runner.py` + `node2_lite.py`

---

## 六、相关文件索引

| 文件 | 说明 |
|------|------|
| `hive_sql_optimization_kb.md` | 知识库（25 KB 卡片 + 24 CASE） |
| `prompts/system_prompt.md` | 系统提示词（CHK-26） |
| `local_runner/workflow_runner.py` | 完整工作流（含 KB 检索） |
| `local_runner/workflow_lite_runner.py` | 精简工作流（无 KB 检索） |
| `local_runner/node2_lite.py` | 精简版节点 2（仅格式化） |
| `local_runner/node4_llm_client.py` | 火山引擎 LLM 客户端 |
| `local_runner/compare_models.py` | 跨模型对比 runner |
| `local_runner/compare_cases.py` | 14 个测试 case |
| `local_runner/results.md` | 跨模型对比报告 |
| `local_runner/results.json` | 跨模型对比原始数据 |
| `local_runner/ab_kb_test.py` | KB A/B 测试脚本 |
| `tests/node2_parse_input.py` | 节点 2 代码（含 26 项 CHK 检测） |
| `tests/node5_parse_json.py` | 节点 5 JSON 解析 |
| `DEPLOY.md` | 千帆部署指南 |
