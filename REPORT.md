# Hive SQL 慢任务智能体 - 对比测试报告

> 日期：2026-06-15
> 引擎：Hive on MR / Tez
> 接口：火山引擎 OpenAI 兼容（https://ark.cn-beijing.volces.com/api/coding/v3）

---

## 一、跨模型对比（CHK-12 版，7 case）

### 1.1 模型排名

| 排名 | 模型 | 平均分 | 总耗时(s) | 全部OK | 平均耗时/case |
|------|------|--------|----------|--------|--------------|
| 1 | **kimi-k2.6** | **1.00** | 122.4 | YES | 17.5 |
| 1 | deepseek-v4-pro | 1.00 | 340.1 | YES | 48.6 |
| 1 | minimax-m3 | 1.00 | 230.0 | YES | 32.9 |
| 1 | doubao-seed-2.0-pro | 1.00 | 307.8 | YES | 44.0 |
| 5 | glm-5.1 | 0.82 | 196.9 | NO | 28.1 |

### 1.2 glm-5.1 失败细节

- **CASE-4**（ORDER BY + select *）：ok=False，JSON 解析失败，0 分
- **CASE-5**（同表重复扫描）：多判 partition_pruning（extra），0.75 分

### 1.3 Token 消耗

| 模型 | prompt_tokens (7 case 合计) | completion_tokens (合计) | total_tokens | 平均/case |
|------|---------------------------|-------------------------|-------------|----------|
| glm-5.1 | 41,027 | 12,649 | 53,676 | 7,668 |
| deepseek-v4-pro | 25,156 | 13,598 | 38,754 | 5,536 |
| **kimi-k2.6** | **26,113** | **12,055** | **38,168** | **5,453** |
| minimax-m3 | 24,542 | 12,829 | 37,371 | 5,339 |
| doubao-seed-2.0-pro | 27,623 | 22,917 | 50,540 | 7,220 |

**5 模型 35 次调用总计**：prompt 144,461 + completion 71,048 = **215,509 tokens**

### 1.4 模型参数对比（仅 kimi-k2.6 vs glm-5.1）

| 参数 | kimi-k2.6 | glm-5.1 |
|------|-----------|---------|
| Context window | 256K | 200K |
| Max output tokens | 4096 | 4096 |
| 输入模态 | text + image | text |
| 对比测试得分 | 1.00 | 0.82 |
| 平均耗时/case | 17.5s | 28.1s |
| 平均 prompt_tokens | 3,730 | 5,866 |
| 平均 completion_tokens | 1,719 | 1,807 |
| reasoning_tokens | 300~500 | 0 |

### 1.5 结论

**kimi-k2.6 是最优选择**：满分 + 速度最快（比第二名快 2.8x）+ token 消耗偏低。

---

## 二、知识库检索 A/B 测试（kimi-k2.6，10 case）

### 2.1 测试设计

- A 组：正常流程（节点 2 关键词检测 → 节点 3 KB 检索 → LLM）
- B 组：跳过 KB 检索，kb_text = "(no knowledge retrieval)"

### 2.2 结果

| Case | With KB | Without KB | Delta | 说明 |
|------|---------|------------|-------|------|
| CASE-1 big-small JOIN + select * | 1.0 | 1.0 | 0 | 无差异 |
| CASE-2 missing partition filter | 1.0 | 1.0 | 0 | 无差异 |
| CASE-3 multi count(distinct) | 1.0 | 1.0 | 0 | 无差异 |
| CASE-4 ORDER BY no LIMIT + select * | 0.0 | 0.0 | 0 | 都失败 |
| CASE-5 same table scanned 3 times | 0.75 | 0.75 | 0 | 无差异 |
| CASE-6 UNION should be UNION ALL | 0.0 | 1.0 | **-1.0** | KB 帮倒忙 |
| CASE-7 clean SQL (fallback) | 1.0 | 1.0 | 0 | 无差异 |
| CASE-8 partition field wrapped | 1.0 | 1.0 | 0 | 无差异 |
| CASE-9 predicate not pushed down | 0.0 | 0.0 | 0 | 都失败 |
| CASE-10 comma JOIN | (超时) | (超时) | - | - |

### 2.3 量化结论

| 指标 | 值 |
|------|-----|
| KB 有帮助的 case | **0 / 10** |
| KB 帮倒忙的 case | **1 / 10** |
| KB 无影响的 case | **9 / 10** |
| 平均分 With KB | 0.575 |
| 平均分 Without KB | 0.675 |
| **KB 净贡献** | **-0.10（负值）** |

### 2.4 原因分析

1. **26 项 CHK 的判断规则已完整写在 system prompt 中**，LLM 不需要额外知识即可做出正确判断
2. **KB chunk 挤占 context window**（6 chunk x 600 字 ≈ 3600 字），可能挤掉有用信息
3. **检索精度有限**：关键词 Jaccard 匹配可能召回不相关 chunk，干扰 LLM 判断（CASE-6 就是例证）
4. **知识库本质是"开卷参考书"**，但对强模型来说规则已内化在 prompt 中，翻书反而可能看错页

### 2.5 结论

**对强模型（kimi-k2.6），知识库检索的贡献为 0 或负数。可以安全移除。**

---

## 三、CHK 覆盖率分析

### 3.1 CHK-12 → CHK-26 升级

| 维度 | CHK-12 | CHK-26 | 增量 |
|------|--------|--------|------|
| CHK 项数 | 12 | 26 | +14 |
| 覆盖 KB 卡片 | 10/20 (50%) | 24/25 (96%) | +14 |
| 覆盖业界高频场景 | ~40% | ~85-90% | +45% |

### 3.2 新增 CHK-13~26 对应场景

| CHK | 场景 | 检测依据 |
|-----|------|---------|
| CHK-13 | 分区字段被函数包裹 | SQL + DDL |
| CHK-14 | 谓词下推缺失 | SQL |
| CHK-15 | JOIN Key 函数转换 | SQL |
| CHK-16 | 老式逗号 JOIN | SQL |
| CHK-17 | 深层嵌套子查询 / 标量子查询 | SQL |
| CHK-18 | OR/AND 优先级错误 | SQL |
| CHK-19 | GROUP BY 潜在倾斜 | SQL + 容量/行数 |
| CHK-20 | JOIN 潜在倾斜 | SQL + 容量 |
| CHK-21 | 动态分区写入未 DISTRIBUTE BY | SQL + DDL |
| CHK-22 | 大 IN 列表 | SQL |
| CHK-23 | LATERAL VIEW EXPLODE 膨胀 | SQL + 容量/行数 |
| CHK-24 | JOIN 两侧字段类型不一致 | SQL + DDL |
| CHK-25 | 同源多次 INSERT | SQL + 容量 |
| CHK-26 | EXISTS 子查询 | SQL |

### 3.3 仍无法仅凭 SQL+DDL+容量+行数检测的场景

| 场景 | 缺什么 |
|------|-------|
| Map 端聚合未触发 | 需执行计划 |
| 分桶未利用 | 需查询是否按桶列过滤 |
| 数据倾斜确认 | 需数据分布统计 |
| JOIN 顺序合理性 | 需中间结果行数估算 |
| 小文件实际数量 | 需 HDFS 文件数统计 |

---

## 四、架构决策

### 4.1 弃用千帆 LLM 节点

| | 千帆 qwen3-coder-30b | 本地 kimi-k2.6 |
|---|---|---|
| 12 CHK 命中 | 2/12（只复读 join_strategy） | 12/12（满分） |
| 速度 | 较慢 | 17.5s/case |
| 指令遵循 | 差 | 强 |

### 4.2 弃用知识库检索

- 千帆向量检索（bge-large-zh）或本地 Jaccard 关键词匹配，对强模型均无正向贡献
- 精简后工作流：`[tables 格式化] → [LLM(26 CHK)] → [JSON 解析]`
- 节点 2 代码从 130 行精简到 15 行

### 4.3 推荐生产配置

| 组件 | 推荐 |
|------|------|
| LLM 模型 | **kimi-k2.6**（首选），deepseek-v4-pro（备选） |
| 接口 | 火山引擎 OpenAI 兼容 |
| KB 检索 | **移除** |
| CHK 项数 | 26 |
| max_tokens | 8192（26 项全命中时输出更长） |
| temperature | 0.1 |

---

## 五、千帆回迁清单（如需）

若回到千帆部署，需更新：

1. **知识库文件**：重新上传新版 `hive_sql_optimization_kb.md`（25 KB + 24 CASE）
2. **节点 2 代码**：替换为 `tests/node2_parse_input.py` 新版（CHK-1~26，中文必须 `\uXXXX` 转义）
3. **节点 4 LLM 模型**：从 qwen3-coder-30b 换成 ERNIE-X1 或 DeepSeek-V3
4. **节点 4 系统提示词**：替换为 `prompts/system_prompt.md` 新版（CHK-26 + data_skew）
5. **节点 4 用户提示词**：更新 Checklist 为 26 项
6. **节点 4 max_tokens**：4096 → 8192

**关键瓶颈仍是模型能力**：千帆若无 ERNIE-X1 级别模型，建议保留本地 runner 方案。

---

## 六、文件索引

| 文件 | 说明 |
|------|------|
| `hive_sql_optimization_kb.md` | 知识库（25 KB 卡片 + 24 CASE） |
| `prompts/system_prompt.md` | LLM 系统提示词（CHK-26） |
| `local_runner/workflow_runner.py` | 完整版 runner（含 KB 检索） |
| `local_runner/workflow_lite_runner.py` | 精简版 runner（无 KB 检索） |
| `local_runner/node2_lite.py` | 精简版节点 2（仅格式化 tables） |
| `local_runner/node4_llm_client.py` | 火山引擎 LLM 客户端 |
| `local_runner/compare_models.py` | 跨模型对比脚本 |
| `local_runner/compare_cases.py` | 测试 case（14 个） |
| `local_runner/ab_kb_test.py` | KB A/B 测试脚本 |
| `local_runner/results.md` | 跨模型对比详细表 |
| `local_runner/results.json` | 跨模型对比原始数据 |
| `tests/node2_parse_input.py` | 节点 2 完整版（CHK-1~26 检测） |
| `tests/node5_parse_json.py` | 节点 5 JSON 解析 |
