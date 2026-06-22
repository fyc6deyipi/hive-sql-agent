# Hive SQL 慢任务优化知识库（合并版）

> **适用引擎**：Hive on MR / Hive on Tez
> **范围**：仅 SQL 写法层面的优化规则
> **使用约束**：智能体必须遵守
> 1. 仅 SQL 写法层面，不输出 set 参数 / 引擎参数
> 2. 不返回完整改写 SQL，仅给出问题点 + 建议方向 + 极简示意（≤3 行）
> 3. 不猜测数据分布；倾斜 / NULL / 热点等只能写"潜在风险，建议人工核查"
> 4. 结论必须有可见证据，来源仅限：SQL 文本 / DDL / 表容量 / 表行数

---

## 知识卡索引

| KB ID | 分类 | 标题 | 严重度 |
|------|-----|-----|-----|
| KB-001 | data_skew | GROUP BY 长尾（潜在风险）| high |
| KB-002 | data_skew | DISTINCT 单点瓶颈 | high |
| KB-003 | data_skew | JOIN 长尾（潜在风险）| high |
| KB-004 | data_skew | 动态分区写入长尾 | medium |
| KB-005 | data_skew | JOIN Key NULL 倾斜（潜在风险）| high |
| KB-010 | pruning | 列裁剪缺失（SELECT *）| medium |
| KB-011 | pruning | 分区裁剪缺失 | high |
| KB-012 | pruning | 分区字段被函数包裹 | high |
| KB-020 | join_strategy | 大小表 JOIN 未走 MapJoin | high |
| KB-021 | join_strategy | JOIN 顺序不合理 | medium |
| KB-022 | join_strategy | 谓词下推缺失 | medium |
| KB-023 | join_strategy | IN/EXISTS 应改 LEFT SEMI JOIN | medium |
| KB-024 | join_strategy | JOIN Key 上有函数转换 | medium |
| KB-025 | join_strategy | JOIN 两侧字段类型不一致 | high |
| KB-026 | join_strategy | EXISTS 子查询应改 LEFT SEMI/ANTI JOIN | medium |
| KB-030 | sql_rewrite | UNION 应改 UNION ALL | low |
| KB-031 | sql_rewrite | COUNT(DISTINCT) 单 Reducer | high |
| KB-032 | sql_rewrite | OR 与 AND 混用未加括号 | high |
| KB-033 | sql_rewrite | 同表多次扫描应 CASE WHEN 合并 | medium |
| KB-034 | sql_rewrite | 嵌套子查询 / 老式逗号 JOIN | medium |
| KB-035 | sql_rewrite | 大 IN 列表字面值过多 | medium |
| KB-036 | sql_rewrite | LATERAL VIEW EXPLODE 行数膨胀 | high |
| KB-037 | sql_rewrite | 同源多次 INSERT 未合并 | medium |
| KB-040 | small_files | 小文件写入风险 | medium |
| KB-050 | sort | 全局 ORDER BY 无 LIMIT | high |

## 真实案例索引

| CASE ID | 标题 | 涉及 KB |
|------|-----|-----|
| CASE-001 | 大表 ORDER BY 全局排序 | KB-010, KB-011, KB-050 |
| CASE-002 | 多表 LEFT JOIN 中间结果膨胀 | KB-010, KB-022 |
| CASE-003 | 缺失分区导致全表扫描 | KB-011 |
| CASE-004 | 同表重复扫描 10 次 | KB-033 |
| CASE-005 | 过多 JOIN 资源浪费 | KB-021, KB-022 |
| CASE-006 | 复杂 SQL 未拆解 | KB-033, KB-034 |
| CASE-007 | DISTINCT 配合疑似倾斜 | KB-002, KB-005 |
| CASE-008 | SELECT * 反模式 | KB-010 |
| CASE-009 | 嵌套 SELECT 老式逗号 JOIN | KB-022, KB-034 |
| CASE-010 | OR 逻辑错误致全表扫描 | KB-032 |
| CASE-011 | 分区字段被函数包裹致裁剪失效 | KB-012 |
| CASE-012 | 多表 JOIN 谓词未下推 | KB-022 |
| CASE-013 | JOIN Key 函数转换致性能退化 | KB-024 |
| CASE-014 | 老式逗号 JOIN | KB-034 |
| CASE-015 | 深层嵌套子查询 | KB-034 |
| CASE-016 | OR/AND 优先级致分区裁剪失效 | KB-032 |
| CASE-017 | 大表 GROUP BY 潜在倾斜 | KB-001 |
| CASE-018 | 大表 JOIN 潜在倾斜 | KB-003, KB-005 |
| CASE-019 | 动态分区写入未 DISTRIBUTE BY | KB-004 |
| CASE-020 | 大 IN 列表致全表扫描 | KB-035 |
| CASE-021 | LATERAL VIEW EXPLODE 行数膨胀 | KB-036 |
| CASE-022 | JOIN 两侧字段类型不一致 | KB-025 |
| CASE-023 | 同源表多次 INSERT 未合并 | KB-037 |
| CASE-024 | EXISTS 子查询应改 LEFT SEMI JOIN | KB-026 |

---

# 一、数据倾斜（Data Skew）

## [KB-001] GROUP BY 长尾（潜在风险）

**分类**: data_skew
**严重度**: high
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- SQL 中包含 `GROUP BY` 子句
- 表行数 > 1 亿（参考 stats.row_count）
- GROUP BY 字段可能是高基数或业务上易热点的列（如 user_id、shop_id、city_id 等）

> 注：是否真的倾斜需要数据分布信息，仅凭 SQL/DDL 无法确认，请按"潜在风险"输出。

### 根因
GROUP BY 时同 key 数据被 Shuffle 到同一个 Reducer。若某些 key 数据量极大，会出现单 Reducer 长尾，整体任务卡在 99%。

### 建议方向（不给出完整改写 SQL）
- 在数仓侧使用统计语句抽样 `GROUP BY key ORDER BY count DESC LIMIT 10`，确认是否存在热点 key
- 若确认热点：将该 key 拆分两阶段聚合（先附加随机后缀打散一次，再外层去掉后缀再聚合）
- 若不确认：用通用打散法，对所有 key 附加随机数做一次预聚合，再做一次聚合

### 极简示意（≤3 行）
```sql
-- 思路示意：GROUP BY key, rand_bucket → 再 GROUP BY key
```

### 是否需要人工核查数据
**是**。GROUP BY 字段的实际值分布无法从 SQL/DDL 判断，需要业务侧抽样统计 Top-N key 的数据量占比。

### 关联
- KB-002 DISTINCT 单点瓶颈
- KB-005 NULL 倾斜
- CASE-007

---

## [KB-002] DISTINCT 单点瓶颈

**分类**: data_skew
**严重度**: high
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- SQL 中包含 `COUNT(DISTINCT col)`、`SELECT DISTINCT ...` 或多个 `COUNT(DISTINCT ...)`
- 表行数 > 1000 万（参考 stats.row_count）
- 尤其是无 GROUP BY 时，单 Reducer 处理全部数据

### 根因
- DISTINCT 需要全局去重，引擎会把所有数据集中到一个 Reducer 才能保证去重正确性
- 与一般倾斜不同，**DISTINCT 即使数据不倾斜也慢**（恒定单点）
- 多个 DISTINCT 同时出现时问题更严重

### 建议方向（不给出完整改写 SQL）
- 单个 `COUNT(DISTINCT col)`：改为外层 `COUNT(1)` + 内层 `GROUP BY col` 的子查询模式
- 多个 `COUNT(DISTINCT col)`：拆为多个子查询分别先 GROUP BY，再合并
- 同时统计 PV 与 UV：先按 uid GROUP BY 算每个 uid 的 PV，再外层 SUM(pv) / COUNT(*)
- 行数小于百万的小表，DISTINCT 影响不大可不改

### 极简示意（≤3 行）
```sql
-- 思路示意：COUNT(DISTINCT uid) → COUNT(1) FROM (SELECT uid FROM t GROUP BY uid)
```

### 是否需要人工核查数据
否（DISTINCT 是结构性单点问题，无需数据分布即可判断）。

### 关联
- KB-001 GROUP BY 长尾
- KB-031 COUNT(DISTINCT) 改写
- CASE-007

---

## [KB-003] JOIN 长尾（潜在风险）

**分类**: data_skew
**严重度**: high
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- SQL 中包含 JOIN
- JOIN 双方都是大表（如均 > 10GB / 行数均上亿）
- JOIN Key 可能是业务热点字段（user_id、product_id、order_id 等）

> 注：是否真倾斜需数据分布信息，仅凭 SQL/DDL/stats 无法确认。

### 根因
JOIN 时相同 key 的两表数据被 Shuffle 到同一个 Instance；若某个 key 数据量过大，该 Instance 处理时间远超其他，形成长尾。

### 建议方向（不给出完整改写 SQL）
- **优先排查能否走 MapJoin**：若一侧明显较小（如 < 100MB），参考 KB-020 添加 MapJoin hint
- 若双方都是大表：建议人工抽样确认 JOIN Key 是否存在热点；如存在，将热点 key 单独拆出 UNION ALL 处理
- 若 JOIN Key 不需要重复匹配：考虑先在子查询中对两侧分别 DISTINCT 去重再 JOIN
- 警惕意外笛卡尔积：若两侧均无过滤、JOIN Key 选择性差，结果集会爆炸

### 极简示意（≤3 行）
```sql
-- 思路示意：热点 key 单独 MapJoin，其余走普通 JOIN，再 UNION ALL
```

### 是否需要人工核查数据
**是**。需抽样统计 JOIN Key 的 Top-N 分布，确认是否存在热点；同时关注 NULL 占比（参见 KB-005）。

### 关联
- KB-005 NULL 倾斜
- KB-020 MapJoin
- KB-024 JOIN Key 上有函数

---

## [KB-004] 动态分区写入长尾

**分类**: data_skew
**严重度**: medium
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- SQL 形如 `INSERT OVERWRITE TABLE t PARTITION(dt) SELECT ..., dt FROM ...`（PARTITION 中的字段无字面值，由 SELECT 提供）
- SELECT 末尾无 `DISTRIBUTE BY 分区列`
- 目标表为分区表（DDL 含 PARTITIONED BY）

### 根因
- 不加 `DISTRIBUTE BY 分区列` 时，每个 Reducer 都可能写入所有目标分区
- 当目标分区数较多时，小文件数 = Reducer 数 × 分区数，急剧膨胀
- 写入完成后的小文件合并阶段或下游读取阶段会出现明显长尾
- 若实际目标分区只有一个，应直接用静态分区

### 建议方向（不给出完整改写 SQL）
- 目标分区在 SQL 中是常量（只写 1 个分区）：将 `PARTITION(dt)` 改为 `PARTITION(dt='YYYYMMDD')` 静态分区
- 目标分区为多个：在 SELECT 末尾加 `DISTRIBUTE BY 分区列`，让每个 Reducer 只写一个分区
- 分区列为多个时全部带上：`DISTRIBUTE BY dt, hour`

### 极简示意（≤3 行）
```sql
-- 思路示意：INSERT ... PARTITION(dt) SELECT ..., dt FROM src DISTRIBUTE BY dt;
```

### 是否需要人工核查数据
否。

### 关联
- KB-040 小文件

---

## [KB-005] JOIN Key NULL 倾斜（潜在风险）

**分类**: data_skew
**严重度**: high
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- SQL 中存在 `LEFT JOIN` / `INNER JOIN`，JOIN Key 为业务字段（如 user_id、device_id）
- 该字段在 DDL 中未声明 NOT NULL（Hive 通常不强制 NOT NULL）
- 字段类型为 string / bigint 等可空类型

> 注：实际 NULL 占比无法从 SQL/DDL 看出，仅能输出潜在风险。

### 根因
所有 NULL 值会因 hash 相同被 Shuffle 到同一个 Reducer，若 NULL 占比较高（一般 >1% 即明显），该 Reducer 成为瓶颈。

### 建议方向（不给出完整改写 SQL）
- 在数仓侧通过 `SELECT count(*) FROM t WHERE key IS NULL OR key = ''` 评估 NULL/空串占比
- 若占比可观（>1%）：在 JOIN ON 条件中将 NULL 替换为带随机后缀的不可匹配值打散
- 业务允许时直接在 WHERE 中过滤掉 NULL（注意 LEFT JOIN 语义改变风险）
- 避免用 `COALESCE(key, 0)` 这种固定值替换 → 会与真实 key=0 冲突

### 极简示意（≤3 行）
```sql
-- 思路示意：ON CASE WHEN a.k IS NULL THEN concat('null_', rand()) ELSE a.k END = b.k
```

### 是否需要人工核查数据
**是**。需人工抽样 JOIN Key 的 NULL / 空字符串 / 默认值（-1、'unknown'、0）占比。建议作为 `needs_human_check` 输出。

### NULL 占比参考表
| 占比 | 影响 | 建议 |
|------|-----|-----|
| < 1% | 几乎无影响 | 不处理 |
| 1% ~ 5% | 中等倾斜 | 建议打散 |
| > 5% | 严重倾斜 | 必须打散 |
| > 20% | 极严重 | 优先处理 |

### 关联
- KB-003 JOIN 长尾
- KB-022 谓词下推

---


# 二、列与分区裁剪（Pruning）

## [KB-010] 列裁剪缺失（SELECT *）

**分类**: pruning
**严重度**: medium
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- SQL 中出现 `SELECT *` 或 `SELECT t.*`（包括最外层和子查询/CTE 内部）
- 涉及表的 DDL 为 `STORED AS ORC` 或 `STORED AS PARQUET` 等列存格式
- 表字段数较多（DDL 中字段 ≥ 5 列）

### 根因
- 列存格式按列读取，`SELECT *` 强制读全部列，IO 数倍放大
- 子查询里的 `SELECT *` 同样浪费：JOIN 前的中间结果集会带上所有字段
- 即使最终只输出几列，中间 JOIN/SHUFFLE 阶段也会传输全部列

### 建议方向（不给出完整改写 SQL）
- 显式列出业务真正使用的字段
- **子查询内同样要列裁剪**：JOIN/UNION 的子查询中也避免 `SELECT *`
- 与下游/业务确认是否真的需要全部列，避免"以防万一"留 `*`

### 极简示意（≤3 行）
```sql
-- 反例：SELECT a.*  /  正例：SELECT a.order_id, a.amount
```

### 是否需要人工核查数据
否（DDL + SQL 即可判定）。

### 收益参考
| 表字段数 | 实际用列 | 浪费比例 |
|---------|---------|---------|
| 50 | 5 | ~90% |
| 30 | 5 | ~83% |
| 10 | 5 | ~50% |

### 关联
- KB-011 分区裁剪
- CASE-008, CASE-002

---

## [KB-011] 分区裁剪缺失

**分类**: pruning
**严重度**: high
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- 表 DDL 含 `PARTITIONED BY (...)`
- SQL 的 WHERE 中**未引用任何分区字段**，或仅在 JOIN 后的外层 WHERE 引用分区字段
- 表容量较大（参考 stats.size_bytes）

### 根因
分区表数据按分区物理存放。未带分区过滤时引擎会扫描全部历史分区。事实表常有数百~数千分区，I/O 放大数十~数百倍。

### 建议方向（不给出完整改写 SQL）
- 在 WHERE 中加入分区字段范围过滤（等值或范围）
- **JOIN 场景下，每张分区表都要带自己的分区过滤**：放在子查询里最稳，避免依赖优化器自动下推
- 分区过滤优先放在 ON 条件或子查询的 WHERE 中，避免放在 JOIN 后的外层 WHERE
- 注意 LEFT JOIN 右表的过滤位置（参见 KB-022）

### 极简示意（≤3 行）
```sql
-- 反例：WHERE create_time >= '2024-01-01'   （未含分区列 dt）
-- 正例：WHERE dt >= '20240101' AND create_time >= '2024-01-01'
```

### 是否需要人工核查数据
否（DDL + SQL 即可判定）。

### 与位置相关的生效规则
| 过滤位置 | 是否生效 |
|---------|--------|
| 子查询内 WHERE | ✅ 最稳 |
| JOIN ON 中包含分区列 | ✅ 生效 |
| 外层 WHERE 上的主表分区 | ✅ 主表生效 |
| 外层 WHERE 上的右表分区（LEFT JOIN）| ⚠️ 易失效 |
| 分区列被函数包裹 | ❌ 失效（参见 KB-012）|

### 关联
- KB-010 列裁剪
- KB-012 分区字段被函数包裹
- KB-022 谓词下推
- CASE-003

---

## [KB-012] 分区字段被函数包裹

**分类**: pruning
**严重度**: high
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- WHERE 子句中虽然引用了分区字段，但分区字段被函数包裹
- 常见形式：`substr(dt, 1, 7) = '202610'`、`year(dt) = 2026`、`to_date(dt, ...) = ...`、`cast(dt as date) >= ...`、`concat(dt, 'x') = ...`
- 或左侧分区字段与右侧值发生隐式类型转换

### 根因
查询优化器需要在编译期就确定要读哪些分区。分区字段被函数包裹后无法静态推导出具体分区值，**分区裁剪失效**，退化为全表扫描。

### 建议方向（不给出完整改写 SQL）
- 把函数运算移到右侧字面量上，让左侧保持原始分区字段
- 等值查询直接用 `=`，范围查询用 `>=` / `<=` / `BETWEEN`
- 业务上需要按月/年聚合的：先用分区范围过滤数据，再在 SELECT 中做聚合维度计算
- 避免分区字段的隐式类型转换：分区字段是 string 就比较 string 字面量

### 改写对照（仅作判断辅助）
| 反例 | 正例方向 |
|------|---------|
| `substr(dt,1,7)='202610'` | `dt >= '20261001' AND dt <= '20261031'` |
| `year(dt)=2026` | `dt >= '20260101' AND dt < '20270101'` |
| `to_date(dt,'yyyymmdd')='2026-10-10'` | `dt = '20261010'` |
| `cast(dt as int) >= 20240101` | `dt >= '20240101'` |

### 是否需要人工核查数据
否。

### 关联
- KB-011 分区裁剪
- KB-024 JOIN Key 上有函数

---


# 三、JOIN 优化（Join Strategy）

## [KB-020] 大小表 JOIN 未走 MapJoin

**分类**: join_strategy
**严重度**: high
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- SQL 中存在 JOIN，两张表的 stats.size_bytes 差异显著
- 通常一张大表（>1GB），另一张小表（如 <100MB）
- SQL 中**未出现** `/*+ MAPJOIN(小表别名) */` 提示
- JOIN 类型支持 MapJoin：INNER JOIN、LEFT JOIN（小表必须在右）、RIGHT JOIN（小表必须在左）

### 根因
- 普通 Common Join 需要把两表都 Shuffle 到 Reducer，大表 shuffle 成本极高
- MapJoin 让小表在 Map 端以 HashMap 形式加载到内存，大表无需 Shuffle，直接在 Map 阶段完成关联
- 性能提升通常 3~10 倍

### 建议方向（不给出完整改写 SQL）
- 在 JOIN 处对小表添加 MapJoin 提示
- 多张小表都符合条件时可同时指定：`/*+ MAPJOIN(b, c) */`
- 注意 JOIN 类型限制：
  - LEFT JOIN：只能广播**右表**
  - RIGHT JOIN：只能广播**左表**
  - FULL OUTER JOIN：不支持，可拆为 LEFT JOIN UNION ALL 后再 MapJoin
- 小表大小有上限（通常 < 512MB，依集群配置而定），过大时可能 OOM
- 评估时若小表是查询结果（如带过滤的子查询），需考虑结果集大小而非原表

### 极简示意（≤3 行）
```sql
-- 思路示意：SELECT /*+ MAPJOIN(b) */ a.col, b.name FROM big_t a JOIN small_t b ON ...
```

### 是否需要人工核查数据
- 建议确认小表容量稳定（不会很快膨胀）
- 若小表是中间结果，需要评估实际产出行数

### 关联
- KB-003 JOIN 长尾
- KB-021 JOIN 顺序

---

## [KB-021] JOIN 顺序不合理

**分类**: join_strategy
**严重度**: medium
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- SQL 涉及 3 张及以上表的 JOIN
- 各表 size_bytes / row_count 差异明显（有 GB 级事实表和 MB 级维度表）
- JOIN 顺序未遵循"小表先 JOIN"：JOIN 链最左侧是最大的表

### 根因
- 多表 JOIN 中，前一阶段的输出会作为后一阶段的输入
- 如果先让两个大表 JOIN，中间结果可能极度膨胀，后续每多一次 JOIN 代价倍增
- 让小表/小结果先参与 JOIN 可使中间数据始终保持较小规模

### 建议方向（不给出完整改写 SQL）
- 按照"小表/选择性强的表先 JOIN"原则调整 JOIN 顺序
- 在每个子查询里**先过滤再 JOIN**（与 KB-022 配合）
- 星型模型：维度表先互 JOIN，再 JOIN 事实表
- 若是雪花模型：同层级维度表先聚合再 JOIN 事实表

### 极简示意（≤3 行）
```sql
-- 反例：FROM big_fact JOIN dim_a JOIN dim_b
-- 正例：FROM dim_a JOIN dim_b JOIN big_fact
```

### 是否需要人工核查数据
否。

### 关联
- KB-020 MapJoin
- KB-022 谓词下推
- CASE-005

---

## [KB-022] 谓词下推缺失（JOIN 后过滤）

**分类**: join_strategy
**严重度**: medium
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- 单表的过滤条件（仅引用一张表的字段）出现在 JOIN 之后的外层 WHERE 中
- 子查询内部未对每张参与表做分区/字段过滤
- LEFT JOIN 的右表过滤条件被放到了外层 WHERE（会让 LEFT JOIN 退化为 INNER JOIN）

### 根因
- 过滤条件在 JOIN 后：先做完整 JOIN 再过滤，参与 Shuffle / Reduce 的数据量很大
- 过滤条件下推到子查询：JOIN 前先过滤，参与 JOIN 的数据量明显减小
- 部分场景优化器能自动下推，但显式写更稳定可控

### 建议方向（不给出完整改写 SQL）
- 把所有"只依赖单表字段"的过滤条件放进对应表的子查询 WHERE 中
- **分区字段必须在子查询内过滤**（详见 KB-011）
- **LEFT JOIN 右表过滤**：放在 ON 条件（`AND b.status='OK'`）或子查询中，不能放外层 WHERE，否则语义改变
- 跨表关联条件（`a.x = b.y`）不能下推，必须保留在 ON 中

### 各类条件的下推规则
| 过滤类型 | 能否下推 |
|---------|--------|
| 分区字段过滤 | ✅ 必须下推 |
| 单表字段等值/范围 | ✅ 推荐下推 |
| 跨表关联条件 | ❌ 必须留在 ON |
| 聚合函数过滤 (HAVING) | ❌ 不能下推 |
| LEFT JOIN 右表过滤 | ⚠️ 需放 ON 或子查询，不能放外层 WHERE |

### 极简示意（≤3 行）
```sql
-- 反例：FROM a JOIN b ON a.id=b.id WHERE a.dt='xxx' AND b.status='OK'
-- 正例：FROM (SELECT ... FROM a WHERE dt='xxx') a JOIN (SELECT ... FROM b WHERE status='OK') b ...
```

### 是否需要人工核查数据
否。

### 关联
- KB-011 分区裁剪
- KB-021 JOIN 顺序
- CASE-002, CASE-005

---

## [KB-023] IN / EXISTS 应改 LEFT SEMI JOIN

**分类**: join_strategy
**严重度**: medium
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- SQL 出现 `WHERE col IN (SELECT col FROM ...)` 或 `WHERE EXISTS (SELECT 1 FROM ...)`
- 子查询基于的表行数较大（>百万）
- 仅需要"左表是否存在匹配"，不需要右表字段

### 根因
- `IN (SELECT ...)` 与 `EXISTS` 在 Hive 中执行效率低于 `LEFT SEMI JOIN`
- `LEFT SEMI JOIN` 是 Hive 专门为半连接场景设计，并行度高
- 同时具有隐式去重特性：左表一行无论右表匹配多少次都只输出一次

### 建议方向（不给出完整改写 SQL）
- 把 `IN (SELECT col FROM t)` 改成 `LEFT SEMI JOIN t ON ...`
- 把 `EXISTS (SELECT 1 FROM t WHERE ...)` 改成 `LEFT SEMI JOIN t ON ...`
- **NOT IN / NOT EXISTS**：改用 `LEFT JOIN ... WHERE 右表字段 IS NULL`

### 限制
- LEFT SEMI JOIN 只能 SELECT **左表**列，不能 SELECT 右表列
- 若需要右表字段，应使用普通 JOIN（并配合去重）

### 极简示意（≤3 行）
```sql
-- 反例：WHERE id IN (SELECT id FROM b)
-- 正例：FROM a LEFT SEMI JOIN b ON a.id = b.id
```

### 是否需要人工核查数据
否。

### 关联
- KB-020 MapJoin
- KB-022 谓词下推

---

## [KB-024] JOIN Key 上有函数转换

**分类**: join_strategy
**严重度**: medium
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- JOIN 的 ON 条件中，一侧或两侧字段被函数包裹：
  - `ON cast(a.id as string) = b.id`
  - `ON lower(a.k) = lower(b.k)`
  - `ON substr(a.code, 1, 5) = b.code`
  - `ON trim(a.k) = b.k`
- 或两侧字段类型不一致触发隐式转换

### 根因
- JOIN Key 上的函数会破坏统计信息和潜在的 sort/bucket 优化
- 数据需要先经过一次函数计算才能 hash 分发，增加 CPU
- 隐式类型转换可能导致优化器选择更保守的执行计划

### 建议方向（不给出完整改写 SQL）
- **从源头对齐字段类型/格式**：在 ETL 上游统一类型与格式（如统一为小写、去空格、统一字段长度），后续 JOIN 直接相等
- 若必须转换，把转换放在子查询里先算出统一字段，再用统一字段做 ON 等值
- 避免在 ON 中使用函数与隐式类型转换

### 极简示意（≤3 行）
```sql
-- 反例：ON cast(a.id as string) = b.id
-- 正例：在子查询中 SELECT cast(id as string) AS id, ...，再用统一字段 JOIN
```

### 是否需要人工核查数据
否。

### 关联
- KB-012 分区字段被函数包裹
- KB-022 谓词下推
- KB-025 JOIN 两侧字段类型不一致

---

## [KB-025] JOIN 两侧字段类型不一致

**分类**: join_strategy
**严重度**: high
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- JOIN ON 条件两侧字段在 DDL 中类型不同，如一侧 `string` 另一侧 `bigint`
- 或一侧 `decimal(18,2)` 另一侧 `double`
- 类型不匹配但 SQL 未显式转换，依赖引擎隐式转换

### 根因
- Hive 在 JOIN 时若两侧字段类型不同，会进行隐式类型转换
- 隐式转换导致：无法利用 sort-merge join / bucket map join 优化
- 转换发生在 Shuffle 阶段，增加 CPU 开销
- 更严重的是 string 与 int 隐式转换时，`'123' = 123` 可能产生意外匹配或不匹配

### 建议方向（不给出完整改写 SQL）
- 在 ETL 上游统一字段类型，确保关联字段类型一致
- 若无法改上游，在子查询中先显式转换类型，再用统一类型做 JOIN
- 避免 JOIN ON 中的隐式转换，显式转换比隐式更可控

### 极简示意（≤3 行）
```sql
-- 反例：ON a.user_id = b.user_id  （a.user_id:string, b.user_id:bigint）
-- 正例方向：在子查询中 SELECT cast(user_id as string) AS user_id，再用统一类型 JOIN
```

### 是否需要人工核查数据
否（DDL 即可判定）。

### 常见类型不一致场景
| 左侧类型 | 右侧类型 | 风险 |
|---------|---------|------|
| string | bigint/int | 隐式转换 + 精度丢失 |
| decimal(p,s1) | decimal(p,s2) | 精度不同导致截断 |
| string | date | 格式依赖隐式解析 |
| int | bigint | 通常安全但不走最优路径 |

### 关联
- KB-024 JOIN Key 上有函数转换
- KB-012 分区字段被函数包裹

---

## [KB-026] EXISTS 子查询应改 LEFT SEMI/ANTI JOIN

**分类**: join_strategy
**严重度**: medium
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- SQL 中出现 `WHERE EXISTS (SELECT ... FROM ... WHERE ...)` 或 `WHERE NOT EXISTS (SELECT ... FROM ... WHERE ...)`
- 子查询基于的表行数较大（> 百万）
- 仅需要判断"是否存在匹配"，不需要子查询表的字段

### 根因
- `EXISTS` / `NOT EXISTS` 子查询在 Hive 中执行效率低于 `LEFT SEMI JOIN` / `LEFT ANTI JOIN`
- `LEFT SEMI JOIN` 是 Hive 专门为半连接设计的语法，并行度更高
- `LEFT SEMI JOIN` 具有隐式去重特性：左表一行无论右表匹配多少次都只输出一次
- `LEFT ANTI JOIN` 专门处理"不存在"场景，比 `NOT EXISTS` 更高效

### 建议方向（不给出完整改写 SQL）
- `WHERE EXISTS (SELECT 1 FROM t WHERE ...)` → `LEFT SEMI JOIN t ON ...`
- `WHERE NOT EXISTS (SELECT 1 FROM t WHERE ...)` → `LEFT ANTI JOIN t ON ...`
- 若子查询表是小表（<100MB），可同时加 MAPJOIN hint
- 若需要子查询表的字段，不能用 LEFT SEMI JOIN，改用普通 JOIN + 去重

### 极简示意（≤3 行）
```sql
-- 反例：WHERE EXISTS (SELECT 1 FROM b WHERE a.id = b.id)
-- 正例：FROM a LEFT SEMI JOIN b ON a.id = b.id
```

### 是否需要人工核查数据
否。

### EXISTS / IN / LEFT SEMI 对比
| 写法 | 语义 | Hive 执行方式 | 推荐度 |
|------|------|-------------|-------|
| WHERE IN (SELECT ...) | 存在 | 依赖优化器改写 | 中 |
| WHERE EXISTS (SELECT ...) | 存在 | 依赖优化器改写 | 中 |
| LEFT SEMI JOIN | 存在 | 原生高效 | 高 |
| WHERE NOT IN (SELECT ...) | 不存在 | 慢 + NULL 陷阱 | 低 |
| WHERE NOT EXISTS (SELECT ...) | 不存在 | 依赖优化器改写 | 中 |
| LEFT ANTI JOIN | 不存在 | 原生高效 | 高 |

### 关联
- KB-023 IN/EXISTS 应改 LEFT SEMI JOIN
- KB-020 MapJoin

---


# 四、SQL 改写（SQL Rewrite）

## [KB-030] UNION 应改 UNION ALL

**分类**: sql_rewrite
**严重度**: low
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- SQL 中使用 `UNION`（注意：Hive 中 `UNION` 等价于 `UNION ALL + DISTINCT`）
- 各分支输出的数据集业务上无重复，或允许重复

### 根因
- `UNION` = `UNION ALL` + 全局 DISTINCT，多一次 Shuffle 去重，开销大
- 若业务确认无重复，去重是多余的，会显著拉长任务时长
- 若确实需要去重，`UNION ALL + GROUP BY` 通常比 `UNION` 更快（可利用 Map 端预聚合）

### 建议方向（不给出完整改写 SQL）
- 业务确认无重复 / 允许重复：改为 `UNION ALL`
- 业务需要去重：使用 `UNION ALL` 后外层加 `GROUP BY 全部列`
- 改写前务必与业务方确认数据语义，避免下游对重复行的依赖

### 极简示意（≤3 行）
```sql
-- 反例：SELECT uid FROM a UNION SELECT uid FROM b
-- 正例：SELECT uid FROM a UNION ALL SELECT uid FROM b
```

### 是否需要人工核查数据
**建议**：与业务方确认结果集是否允许重复，避免改写后下游报错。

### 关联
- KB-001 GROUP BY 长尾

---

## [KB-031] COUNT(DISTINCT) 单 Reducer

**分类**: sql_rewrite
**严重度**: high
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- SQL 包含 `COUNT(DISTINCT col)`
- 表行数 > 100 万
- 可能出现多个 `COUNT(DISTINCT col1), COUNT(DISTINCT col2)`

### 根因
- DISTINCT 需要全局唯一性，Hive 通常用单 Reducer 实现
- 单 Reducer 处理所有数据成为恒定瓶颈，即使数据不倾斜也慢
- 多个 DISTINCT 同时出现时更严重，每个 DISTINCT 都是独立全表去重

### 建议方向（不给出完整改写 SQL）
- 单个 COUNT(DISTINCT)：改为外层 `COUNT(1)` + 内层子查询 `GROUP BY col`（GROUP BY 可走多 Reducer 并行）
- PV + UV 同时算：先按 uid GROUP BY 算每个 uid 的 PV，再外层 `SUM(pv)` / `COUNT(*)`
- 多个 DISTINCT：拆为多个子查询分别 GROUP BY，再用 JOIN 或 CROSS JOIN 合并结果
- 分组 + DISTINCT（如 `GROUP BY category, COUNT(DISTINCT uid)`）：先按 `category, uid` GROUP BY 去重，再按 category 二次聚合 COUNT(*)

### 极简示意（≤3 行）
```sql
-- 思路示意：COUNT(DISTINCT uid) → COUNT(1) FROM (SELECT uid FROM t GROUP BY uid)
```

### 是否需要人工核查数据
否。但若 DISTINCT 列本身存在严重倾斜，改写后仍可能在 GROUP BY 阶段倾斜，需配合 KB-001 评估。

### 收益参考
| 行数 | 原始 | 改写后 |
|------|-----|--------|
| 100 万 | 30s | 25s |
| 1000 万 | 5 min | 1 min |
| 1 亿 | 30 min | 3 min |
| 10 亿 | 跑不出 | 15 min |

### 关联
- KB-002 DISTINCT 单点
- CASE-007

---

## [KB-032] OR 与 AND 混用未加括号

**分类**: sql_rewrite
**严重度**: high
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- WHERE / ON 子句中同时出现 `OR` 与 `AND`
- 没有用括号明确优先级
- 涉及分区字段时风险最大：可能因优先级导致分区裁剪部分失效，触发全表扫描

### 根因
逻辑优先级：`NOT > AND > OR`。
不加括号时 `A AND B OR C AND D` 等价于 `(A AND B) OR (C AND D)`；
若期望是 `A AND (B OR C) AND D`，必须显式加括号。
分区字段过滤如果落入了 OR 的某一侧而另一侧没有分区过滤，**该 OR 分支会全表扫描**。

### 建议方向（不给出完整改写 SQL）
- 任何 `AND` / `OR` 混用都强制加括号
- 分区字段过滤建议用 `AND` 串到最外层，确保所有 OR 分支都被分区裁剪覆盖
- 明确业务意图：常见误用是把"非空 OR 不等于空串"写成 OR（应为 AND）
- 多个等值条件用 `IN (...)` 替代多个 `=` + `OR`，更清晰

### 极简示意（≤3 行）
```sql
-- 反例：WHERE a=1 AND b=2 OR c=3   （等价 (a=1 AND b=2) OR c=3）
-- 正例：WHERE (a=1 AND b=2) OR c=3  或  WHERE a=1 AND (b=2 OR c=3)
```

### 是否需要人工核查数据
否，但**建议同时核查执行计划**（EXPLAIN）确认分区裁剪生效。

### 自检清单
- [ ] WHERE 中是否有 OR？
- [ ] OR 周围是否有括号？
- [ ] 括号位置是否与业务语义一致？
- [ ] 改写后是否所有 OR 分支都包含了分区过滤？

### 关联
- KB-011 分区裁剪
- CASE-010

---

## [KB-033] 同表多次扫描应 CASE WHEN 合并

**分类**: sql_rewrite
**严重度**: medium
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- 同一张表（特别是大表，>GB / >亿行）在 SQL 中被多次 FROM
- 多个 JOIN 子查询基于同一张表，只是 WHERE 过滤值不同
- 或多个 UNION ALL 分支来源同一张表，只是过滤条件不同

### 根因
- 每个子查询都触发一次表扫描，大表扫描成本极高
- 重复扫描数倍于一次扫描的成本
- 引擎一般不会自动合并相同来源的子查询

### 建议方向（不给出完整改写 SQL）
- **JOIN 多个分支：用 GROUP BY + CASE WHEN MAX/SUM 合并**：一次扫描表，按不同条件聚合出多个列，再统一 JOIN 到主表
- **UNION ALL 多分支：用 CASE WHEN 输出多列**：一次扫描表，每行按条件归类
- **多路写出**：使用 `FROM t INSERT OVERWRITE TABLE t1 SELECT ... INSERT OVERWRITE TABLE t2 SELECT ...` 多路插入语法
- 频繁被使用的大表，可考虑在脚本前置一段，将常用过滤后的中间结果写入临时表，后续复用

### 极简示意（≤3 行）
```sql
-- 思路示意：
-- SELECT pid, MAX(CASE WHEN type='A' THEN ts END) ta, MAX(CASE WHEN type='B' THEN ts END) tb FROM t GROUP BY pid
```

### 是否需要人工核查数据
否。

### 收益参考
| 重复扫描次数 | 性能提升 |
|------------|---------|
| 5 次 | 4~5x |
| 10 次 | 8~10x |
| 20 次 | 15~20x |

### 关联
- KB-022 谓词下推
- CASE-004, CASE-006

---

## [KB-034] 嵌套子查询 / 老式逗号 JOIN

**分类**: sql_rewrite
**严重度**: medium
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- 子查询嵌套深度 ≥ 3 层
- 使用老式逗号 JOIN 语法：`FROM a, b, c WHERE a.id=b.id AND b.id=c.id`
- SELECT 列表中出现标量子查询：`SELECT (SELECT ... FROM t WHERE ...) AS col FROM ...`

### 根因
- 老式逗号 JOIN 不利于优化器识别 JOIN 模式
- 多层嵌套时优化器难以做有效的谓词下推
- SELECT 列表中的子查询每输出一行都可能触发一次扫描（即使 Hive 会改写，可读性也很差）

### 建议方向（不给出完整改写 SQL）
- SELECT 列表中的子查询 → 改为外层 LEFT JOIN，把子查询要的列通过 JOIN 一次性带出
- 老式逗号 JOIN → 改为显式 `JOIN ... ON ...`，过滤分两类：JOIN 条件放 ON，单表过滤放子查询
- 多层嵌套 → 用 CTE（`WITH x AS (...), y AS (...)`）扁平化，每个 CTE 内部做好分区和列裁剪
- 注意：CTE 在 Hive 中是逻辑视图，内部仍需做好过滤下推

### 极简示意（≤3 行）
```sql
-- 反例：SELECT (SELECT name FROM dim WHERE id=a.id) FROM a
-- 正例：SELECT d.name FROM a LEFT JOIN dim d ON d.id = a.id
```

### 是否需要人工核查数据
否。

### 关联
- KB-022 谓词下推
- KB-033 同表多次扫描
- CASE-006, CASE-009

---

## [KB-035] 大 IN 列表字面值过多

**分类**: sql_rewrite
**严重度**: medium
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- WHERE 子句中 `IN (v1, v2, ...)` 的字面值数量 > 100
- 或多个 IN 条件叠加，总字面值数量 > 200
- IN 列表作用在大表（> 1GB）上

### 根因
- Hive 解析大 IN 列表时会展开为 OR 链（`col=v1 OR col=v2 OR ...`），超长 OR 链导致：
  - 解析阶段耗时显著增加
  - 优化器生成计划困难，可能放弃部分优化
  - 执行时退化为逐值比较而非 hash 查找
- 当 IN 列表值超过几千时，任务启动阶段就可能卡住数分钟

### 建议方向（不给出完整改写 SQL）
- 将 IN 列表中的值存入临时表或维度表，用 JOIN 替代 IN
- 若值来自另一张表：直接用 `IN (SELECT col FROM t)` 或 `LEFT SEMI JOIN`（参见 KB-023/KB-026）
- 若值范围连续：改用 `BETWEEN ... AND ...` 或 `>= ... AND <= ...`
- 若值有业务分类规律：改用分类字段过滤

### 极简示意（≤3 行）
```sql
-- 反例：WHERE city_id IN (110001, 110002, ..., 共500个)
-- 正例方向：将城市列表存入临时表 dim_city，用 LEFT SEMI JOIN 替代
```

### 是否需要人工核查数据
否。

### IN 列表规模参考
| 字面值数量 | 影响 |
|-----------|------|
| < 50 | 基本无影响 |
| 50 ~ 200 | 解析变慢，建议优化 |
| 200 ~ 1000 | 明显影响解析和执行 |
| > 1000 | 严重，必须改写 |

### 关联
- KB-023 IN/EXISTS 应改 LEFT SEMI JOIN
- KB-026 EXISTS 子查询

---

## [KB-036] LATERAL VIEW EXPLODE 行数膨胀

**分类**: sql_rewrite
**严重度**: high
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- SQL 中出现 `LATERAL VIEW EXPLODE(...)` 或 `LATERAL VIEW OUTER EXPLODE(...)`
- 源表为大表（size > 10GB 或行数 > 1亿）
- EXPLODE 的字段为数组或 Map 类型（DDL 中为 `array<...>` / `map<...>`）

### 根因
- EXPLODE 将每行的数组/Map 展开为多行，行数膨胀倍数 = 数组/Map 的平均元素数
- 若数组平均 10 个元素，1 亿行膨胀为 10 亿行
- 膨胀后的数据在后续 JOIN / GROUP BY / ORDER BY 中成本成倍增长
- `LATERAL VIEW`（非 OUTER）会过滤掉数组为空的行，可能丢失数据

### 建议方向（不给出完整改写 SQL）
- 先在子查询中过滤掉不需要的行，再 EXPLODE，减少膨胀基数
- 若只需要数组中满足某条件的元素：先 `LATERAL VIEW EXPLODE` 再在 WHERE 过滤，或用 `array_contains` 先判断再展开
- 若只需要判断数组中是否存在某元素：用 `array_contains(arr, val)` 替代 EXPLODE + WHERE
- 若需要统计数组元素个数：用 `size(arr)` 替代 EXPLODE + COUNT

### 极简示意（≤3 行）
```sql
-- 反例：SELECT id, item FROM big_t LATERAL VIEW EXPLODE(items) t AS item  （items 平均 20 个元素）
-- 正例方向：先 WHERE 过滤缩小范围，再 EXPLODE；或用 array_contains 替代
```

### 是否需要人工核查数据
**是**。需抽样评估数组字段的平均元素个数，确认膨胀倍数。

### 关联
- KB-010 列裁剪
- KB-022 谓词下推

---

## [KB-037] 同源多次 INSERT 未合并

**分类**: sql_rewrite
**严重度**: medium
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- 同一个脚本/SQL 中出现 ≥ 2 个 `INSERT INTO/OVERWRITE` 语句
- 多个 INSERT 的 FROM 子句扫描同一张源表
- 源表为大表（> 1GB）

### 根因
- 每个 INSERT 语句独立执行，对源表各扫描一次
- 同一张大表被扫描 N 次（N = INSERT 语句数），I/O 和计算资源浪费 N 倍
- Hive 支持 multi-insert 语法，一次扫描源表、多路写出

### 建议方向（不给出完整改写 SQL）
- 使用 Hive multi-insert 语法：`FROM source_table INSERT INTO t1 SELECT ... INSERT INTO t2 SELECT ...`
- 一次扫描源表，多路写出不同目标表
- 若目标表结构相似，可合并为一个 INSERT + 条件列区分
- 若 INSERT 之间有依赖（后一个依赖前一个的输出），则无法合并

### 极简示意（≤3 行）
```sql
-- 反例：INSERT INTO t1 SELECT ... FROM big_t WHERE ...; INSERT INTO t2 SELECT ... FROM big_t WHERE ...;
-- 正例：FROM big_t INSERT INTO t1 SELECT ... WHERE ... INSERT INTO t2 SELECT ... WHERE ...
```

### 是否需要人工核查数据
否。

### 关联
- KB-033 同表多次扫描
- KB-034 嵌套子查询

---


# 五、小文件治理（Small Files）

## [KB-040] 小文件写入风险

**分类**: small_files
**严重度**: medium
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- 动态分区写入未配合 `DISTRIBUTE BY 分区列`（参见 KB-004）
- 写入语句末尾使用了大量 reducer 但写入数据量小
- SQL 末尾出现 `DISTRIBUTE BY rand()` 但桶数过大（造成每桶小文件）

### 根因
- Reducer 数过多 + 数据量小 → 每个 Reducer 产出的文件很小
- 动态分区中每个 Reducer 写所有目标分区 → 文件数 = Reducer 数 × 分区数
- 大量小文件会拖慢下游任务（每个文件至少一个 mapper）

### 建议方向（不给出完整改写 SQL）
- 动态分区写入：末尾加 `DISTRIBUTE BY 分区列`，让每个 Reducer 只写一个分区
- 写入数据量较小时：可用 `DISTRIBUTE BY rand()` 配合较小的桶数（如 mod 几）控制 Reducer 数
- 历史已存在的小文件可用 `ALTER TABLE ... CONCATENATE`（仅 ORC）做合并，但需谨慎评估
- 避免单次 SQL 写入数 KB ~ 数 MB 量级的极小分区

### 极简示意（≤3 行）
```sql
-- 思路示意：INSERT ... PARTITION(dt) SELECT ..., dt FROM src DISTRIBUTE BY dt;
```

### 是否需要人工核查数据
- 建议核查目标表当前分区平均文件数与大小

### 关联
- KB-004 动态分区长尾

---


# 六、排序优化（Sort）

## [KB-050] 全局 ORDER BY 无 LIMIT

**分类**: sort
**严重度**: high
**适用引擎**: Hive on MR / Tez

### 识别特征（智能体可静态判断）
- SQL 最外层（或单一查询块）含 `ORDER BY` 且**未带 LIMIT**
- 表行数较大（参考 stats.row_count，通常 > 100 万）
- 业务上经常只需要"最新一条 / TOP-N / 局部有序"

### 根因
- `ORDER BY` 是全局排序，所有数据被 Shuffle 到**同一个 Reducer**
- 单 Reducer 处理全表数据，CPU/内存吃满
- 无 LIMIT 时无法优化（无法每 Reducer 各自取 TOP-N 后再合并）

### 建议方向（不给出完整改写 SQL）
- "只要最新一条"：用 `MAX/MIN` 直接取目标字段
- "TOP-N"：加 `LIMIT N`，引擎可优化为每 Reducer 取 TOP-N 后再合并
- "每个分组的 TOP-N"：用窗口函数 `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...) <= N`
- "只要局部有序"：改用 `DISTRIBUTE BY x SORT BY y`，多 Reducer 并行
- "全量导出后排序"：在下游关系数据库（MySQL / ADB 等）做排序，不要在 Hive 全排

### 排序语法对比
| 语法 | Reducer 数 | 排序范围 |
|------|----------|---------|
| ORDER BY | 1 | 全局 |
| SORT BY | N | 每 Reducer 内 |
| DISTRIBUTE BY | N | 不排序，仅控分发 |
| CLUSTER BY | N | = DISTRIBUTE BY + SORT BY |

### 极简示意（≤3 行）
```sql
-- 反例：SELECT * FROM big_t ORDER BY ts DESC
-- 正例：SELECT * FROM big_t ORDER BY ts DESC LIMIT 100
```

### 是否需要人工核查数据
否。但建议向业务确认是否真的需要全局有序的完整结果集。

### 关联
- KB-010 列裁剪
- KB-011 分区裁剪
- CASE-001

---


# 七、真实慢 SQL 案例（Cases）

## [CASE-001] 大表 ORDER BY 全局排序

**关联 KB**: KB-010, KB-011, KB-050
**严重度**: high

### 业务场景
查询某宽表"最新数据日期"。

### 问题 SQL
```sql
SELECT *
FROM js_ods_prod.ods_yxyw_fdpshare_e_mp_power_curve
ORDER BY data_date DESC;
```

### 问题诊断
1. **KB-010** `SELECT *` 列存表无列裁剪
2. **KB-011** 表为分区表但 WHERE 缺失分区过滤 → 扫全部历史分区
3. **KB-050** `ORDER BY ... DESC` 无 LIMIT → 单 Reducer 全局排序

### 建议方向
- 业务真实意图是"取最新日期"，建议使用 `MAX(data_date)` 取最值，无需全局排序
- 必须在 WHERE 中加入分区字段（如 `ds = 'YYYYMMDD'`）做分区裁剪
- 只取业务需要的列，禁用 `SELECT *`

### 是否需要人工核查
确认业务确实只需要"最新日期"而非排序后的完整结果集。

---

## [CASE-002] 多表 LEFT JOIN 中间结果膨胀

**关联 KB**: KB-010, KB-022
**严重度**: high

### 业务场景
ERP 物料库存表关联 10+ 维度表生成宽表，每个子查询都使用 `SELECT *`。

### 问题 SQL（节选）
```sql
INSERT OVERWRITE TABLE QRYG_W_ERP_KL PARTITION(ds='20201021')
SELECT [20+列]
FROM (SELECT * FROM DWD_MAT_PROJECTINVENTORY WHERE ds='20201021') t1
LEFT JOIN (SELECT * FROM ERP_CD_T001W WHERE ds='20201021') t2 ON ...
LEFT JOIN (SELECT * FROM DWD_MAT_MATBASICINF WHERE ds='20201021') t3 ON ...
-- 共 12 个 LEFT JOIN，每个子查询都 SELECT *
```

### 问题诊断
1. **KB-010** 每个 LEFT JOIN 的子查询都 `SELECT *`，导致 JOIN 中间结果集携带所有字段
2. **KB-022** 子查询内的分区过滤已下推，但**列**未下推，中间结果膨胀
3. **KB-021**（潜在）12 个 JOIN 未按表大小排序，且未做表大小评估

### 建议方向
- 每个子查询里**只 SELECT 后续真正使用的字段**（包括 JOIN Key + 最终输出列）
- 评估是否能让小维度表使用 MapJoin（参见 KB-020）
- 评估 JOIN 顺序是否合理（小表/选择性强的先 JOIN）

### 是否需要人工核查
请核查每张维度表的实际容量（size_bytes），判断哪些可走 MapJoin。

---

## [CASE-003] 缺失分区导致全表扫描

**关联 KB**: KB-011, KB-022
**严重度**: high

### 业务场景
查询订单表某天的数据，但 WHERE 中只过滤了业务字段，未过滤分区字段。

### 问题 SQL
```sql
SELECT order_id, amount, create_time
FROM dwd_order
WHERE create_time >= '2024-01-01' AND status = 'PAID';
```

DDL：
```sql
CREATE TABLE dwd_order (...) PARTITIONED BY (dt string) STORED AS ORC;
```

### 问题诊断
1. **KB-011** 表为分区表（PARTITIONED BY dt），但 WHERE 中未引用分区字段 dt → 全部历史分区被扫描
2. `create_time` 是普通字段而非分区字段，对其过滤无法剪枝分区文件

### 建议方向
- 在 WHERE 中加入分区字段范围过滤（如 `dt >= '20240101'`）
- `create_time` 的过滤仍保留，作为分区内的行级过滤
- 如分区粒度是天，且业务只查某天，使用等值过滤 `dt = 'YYYYMMDD'` 最优

### 是否需要人工核查
否（DDL + SQL 即可判定）。

---

## [CASE-004] 同表重复扫描

**关联 KB**: KB-033
**严重度**: high

### 业务场景
关联活动事实表，按 10 个环节定义名（link_define_nm）分别取 end_tm 字段，生成宽表。

### 问题 SQL（节选）
```sql
LEFT JOIN (SELECT process_id, end_tm FROM FCT_CST_ACTIVITY_D WHERE link_define_nm='答复供电方案') c ON ...
LEFT JOIN (SELECT process_id, end_tm FROM FCT_CST_ACTIVITY_D WHERE link_define_nm='业务受理')   aa ON ...
LEFT JOIN (SELECT process_id, end_tm FROM FCT_CST_ACTIVITY_D WHERE link_define_nm='设计文件受理') d ON ...
-- 共 10 个类似 JOIN，全部来自同一张大表
```

### 问题诊断
1. **KB-033** 同一张大表 `FCT_CST_ACTIVITY_D` 被扫描 10 次
2. 重复扫描成本数倍于一次扫描；表越大代价越高

### 建议方向
- 一次扫描 + `GROUP BY process_id` + 10 个 `MAX(CASE WHEN link_define_nm='xxx' THEN end_tm END)`
- 把"按 process_id 透视"的结果作为单一子查询 JOIN 回主表
- 若该宽表后续仍被其他任务使用，可以将该子查询沉淀为中间临时表

### 是否需要人工核查
否。

---

## [CASE-005] 过多 JOIN 资源浪费

**关联 KB**: KB-021, KB-022, KB-010
**严重度**: high

### 业务场景
一段 ETL 在一个 SELECT 块中连续 JOIN 了 8 张表，所有过滤条件都堆在最外层 WHERE。

### 问题特征
```sql
SELECT ...
FROM big_fact f
LEFT JOIN dim_a a ON f.k = a.k
LEFT JOIN dim_b b ON f.k = b.k
LEFT JOIN dim_c c ON a.k = c.k
LEFT JOIN big_aux x ON f.k = x.k
...
WHERE f.dt = '20261010'
  AND a.status = 'OK'
  AND b.type IN ('1', '2')
  AND x.dt = '20261010';
```

### 问题诊断
1. **KB-022** 各表的过滤条件（`a.status`、`b.type`、`x.dt`）全部在外层 WHERE，没有下推到子查询，参与 JOIN 的数据量没有任何缩减
2. **KB-021**（潜在）8 张表 JOIN 未按表大小/选择性排序
3. **KB-010**（潜在）若各表 `SELECT *`，中间结果集会同时膨胀列数与行数

### 建议方向
- 每张表用子查询包裹，先做"只该表能做的过滤"（含分区过滤 + 字段过滤）再 JOIN
- 评估各表大小，将小维表先互相 JOIN 再 JOIN 大事实表
- 对明显是小维表的（如 `dim_a`、`dim_b`）评估是否走 MapJoin（KB-020）
- 子查询中也要做列裁剪

### 是否需要人工核查
请核查各维度表的容量与行数，判断 JOIN 顺序与 MapJoin 适用性。

---

## [CASE-006] 复杂 SQL 未拆解

**关联 KB**: KB-033, KB-034
**严重度**: medium

### 业务场景
一个 SQL 文件长达 300+ 行，包含 5 层子查询嵌套、4 次同表扫描、若干 SELECT 列表里的标量子查询。

### 问题特征
- 多层嵌套子查询，每层都有不同的过滤与聚合
- 同一张维表在不同子查询中重复 JOIN
- SELECT 中出现 `(SELECT name FROM dim WHERE id = a.id)` 标量子查询

### 问题诊断
1. **KB-034** 嵌套过深导致优化器难以做谓词下推，可读性差
2. **KB-033** 同表重复扫描，未合并为一次扫描多分支
3. SELECT 列表标量子查询应改为 LEFT JOIN

### 建议方向
- 用 CTE（`WITH x AS ..., y AS ...`）将多层子查询扁平化，每个 CTE 内部做好列/分区裁剪
- 同表多次扫描合并：参考 KB-033 用 CASE WHEN + GROUP BY 一次性产出多分支结果
- 标量子查询改为 LEFT JOIN，把要的列通过 JOIN 一次性带出
- 复杂任务可拆分为多个 INSERT 语句，先沉淀中间表再使用

### 是否需要人工核查
否。

---

## [CASE-007] DISTINCT 配合疑似倾斜

**关联 KB**: KB-002, KB-005, KB-031
**严重度**: high

### 业务场景
按渠道维度计算 UV：`SELECT channel, COUNT(DISTINCT uid) FROM logs WHERE dt='...' GROUP BY channel`。任务运行 3 小时未结束。

### 问题诊断
1. **KB-002** `COUNT(DISTINCT uid)` 是 Hive 中的单 Reducer 操作（按 channel 分组后每个 channel 仍是单 Reducer 处理 DISTINCT）
2. **KB-005**（潜在）若 `uid` 字段存在大量 NULL/空串，会形成额外 hash 倾斜
3. 渠道分布如果严重不均（如 90% 流量来自 1 个渠道），单分区 Reducer 会成为长尾

### 建议方向
- 改写为两阶段 GROUP BY：先按 `(channel, uid)` GROUP BY 去重，再按 `channel` 做 `COUNT(*)`（参见 KB-031）
- 若 uid 存在大量 NULL：先在子查询中过滤掉 NULL/空串再统计
- 若仍倾斜：抽样确认 channel 分布；对热点 channel 单独处理（参考 KB-001 的两阶段聚合思路）

### 是否需要人工核查
**是**：
- 抽样 `uid` 的 NULL/空串占比
- 抽样 `channel` 的 Top-N 分布，确认是否存在热点

---

## [CASE-008] SELECT * 反模式

**关联 KB**: KB-010
**严重度**: medium

### 业务场景
报表查询从一张 80 字段的 ORC 大表中只展示 5 个字段，但 SQL 写成了 `SELECT *`。

### 问题 SQL
```sql
SELECT *
FROM dwd_user_behavior
WHERE dt = '20261010';
```

DDL 显示该表有 80 个字段，存储格式为 ORC。

### 问题诊断
1. **KB-010** ORC 列存格式按列读取，`SELECT *` 强制读取全部 80 列
2. 即使最终只展示 5 列，IO 与网络传输放大约 16 倍
3. 列存的列裁剪 / 列编码优势完全失效

### 建议方向
- 显式列出展示需要的 5 个字段
- 全行业务规范禁用 `SELECT *`（除非真的需要所有列）
- 子查询内也要遵守列裁剪（与 CASE-002 相同教训）

### 是否需要人工核查
确认下游展示侧是否真的只需要 5 列。

---

## [CASE-009] 嵌套 SELECT 老式写法

**关联 KB**: KB-034, KB-022
**严重度**: medium

### 业务场景
一段历史 SQL 使用老式逗号 JOIN，5 张分区表的过滤条件全部堆在 WHERE 中。

### 问题 SQL（节选）
```sql
SELECT r.*, t.SORT_CODE, c.SGNAME
FROM DWD_CST_ITRUN r,
     DWD_CST_MP P,
     DWD_CST_CONSUMER c,
     DWD_CST_MPITRELA m,
     UN14_02_CMS_D_IT t
WHERE r.ITID = m.ITID
  AND m.MPID = P.MPID
  AND P.CONSID = c.CONSID
  AND r.ITID = t.IT_ID
  AND t.SORT_CODE IN ('01','03','04')
  AND c.SGSTATUS < '9'
  AND r.CURRENTRATIO IS NULL
  AND r.ds = '${bizdate}'
  AND P.ds = '${bizdate}'
  AND c.ds = '${bizdate}'
  AND m.ds = '${bizdate}'
  AND t.ds = '${bizdate}';
```

### 问题诊断
1. **KB-034** 老式逗号 JOIN，对优化器和阅读都不友好
2. **KB-022** 各表的过滤（分区过滤、`SORT_CODE IN`、`SGSTATUS < '9'`）全部在外层 WHERE，没有下推到各表子查询
3. **KB-010** 出现 `r.*` 全列引用

### 建议方向
- 改为显式 `JOIN ... ON ...` 语法，JOIN Key 放 ON，单表过滤放子查询 WHERE
- 每张表都用子查询包裹做分区过滤 + 字段过滤 + 列裁剪
- `r.*` 改为只取业务真正用到的字段

### 是否需要人工核查
否。

---

## [CASE-010] OR 逻辑错误导致全表扫描

**关联 KB**: KB-032, KB-011
**严重度**: critical

### 业务场景
监控某扩展字段是否被更新，原本只查询 2 个分区，实际任务扫描了全表 197 亿条数据。

### 问题 SQL
```sql
SELECT *
FROM xxx_extend
WHERE extend_field_1 = ''
  AND extend_field_update_time IS NOT NULL
  AND extend_field_update_time <> ''
  AND ds IN (20201128, 20201129)
   OR extend_field_1 IS NOT NULL;
```

### 问题诊断
1. **KB-032** 由于优先级 `AND > OR`，实际语义等价于：
   ```
   (extend_field_1 = '' AND ... AND ds IN (...)) OR extend_field_1 IS NOT NULL
   ```
   后一条 `extend_field_1 IS NOT NULL` 独立成条件且**没有分区过滤**
2. **KB-011** 后半分支没有 `ds` 过滤 → 全部历史分区被扫描
3. 业务意图大概率是"字段非空（非 NULL 且非空字符串）"——本应是 AND，被错写为 OR

### 建议方向
- 立即用括号明确语义：所有 OR 分支必须显式包裹，且分区过滤应在所有分支都生效
- 与业务方核对"OR"是否真的是业务意图；如果是想表达"字段非空"应使用 `AND` 或 `<> '' AND IS NOT NULL`
- 加完括号后用 `EXPLAIN` 确认分区裁剪生效

### 是否需要人工核查
**强烈建议**核查该 OR 是否表达业务真实意图。

---

## [CASE-011] 分区字段被函数包裹致裁剪失效

**关联 KB**: KB-012, KB-011
**严重度**: high

### 业务场景
按月汇总订单数据，WHERE 中用 `substr(dt,1,6)` 过滤分区字段，导致分区裁剪失效，全表扫描。

### 问题 SQL
```sql
SELECT order_id, amount
FROM dwd_order
WHERE substr(dt, 1, 6) = '202610';
```

DDL：
```sql
CREATE TABLE dwd_order (
  order_id string, amount decimal(18,2), create_time string
) PARTITIONED BY (dt string) STORED AS ORC;
```

### 问题诊断
1. **KB-012** 分区字段 `dt` 被 `substr()` 函数包裹，优化器无法静态推导分区值，分区裁剪失效
2. **KB-011** 虽然引用了分区字段，但因函数包裹等效于未引用，扫描全部历史分区

### 建议方向
- 将函数运算移到右侧：`dt >= '20261001' AND dt <= '20261031'`
- 保持左侧分区字段为原始字段名，让优化器可推导分区范围

### 是否需要人工核查
否。

---

## [CASE-012] 多表 JOIN 谓词未下推

**关联 KB**: KB-022, KB-011
**严重度**: high

### 业务场景
事实表关联 3 张维度表，所有过滤条件堆在外层 WHERE，JOIN 中间结果未缩减。

### 问题 SQL
```sql
SELECT f.order_id, a.region_name, b.category_name, c.pay_type_name
FROM dwd_order_fact f
LEFT JOIN dim_region a ON f.region_id = a.region_id
LEFT JOIN dim_category b ON f.category_id = b.category_id
LEFT JOIN dim_pay_type c ON f.pay_type_id = c.pay_type_id
WHERE f.dt = '20261010'
  AND a.is_active = 1
  AND b.level = 1
  AND c.is_enabled = 'Y';
```

### 问题诊断
1. **KB-022** 各维度表的单表过滤（`a.is_active`、`b.level`、`c.is_enabled`）全在外层 WHERE，未下推到子查询
2. **KB-022** LEFT JOIN 右表过滤条件放外层 WHERE 会导致 LEFT JOIN 退化为 INNER JOIN
3. **KB-011** 维度表的分区字段 `dt` 也未在各子查询中过滤

### 建议方向
- 每张维度表用子查询包裹，先做分区过滤 + 字段过滤 + 列裁剪再 JOIN
- LEFT JOIN 右表的过滤条件放 ON 或子查询，避免语义改变

### 是否需要人工核查
否。

---

## [CASE-013] JOIN Key 函数转换致性能退化

**关联 KB**: KB-024
**严重度**: medium

### 业务场景
两张大表 JOIN，ON 条件中对一侧 key 做了 `lower()` 函数转换。

### 问题 SQL
```sql
SELECT a.order_id, b.user_name
FROM dwd_order a
JOIN dwd_user b ON lower(a.user_id) = lower(b.user_id)
WHERE a.dt = '20261010';
```

### 问题诊断
1. **KB-024** JOIN ON 中 `lower(a.user_id)` 破坏了 sort-merge join 和 bucket map join 优化
2. 数据需先经函数计算再 hash 分发，增加 CPU 开销

### 建议方向
- 在 ETL 上游统一 user_id 的大小写格式
- 若无法改上游，在子查询中先 `SELECT lower(user_id) AS user_id`，再用统一字段 JOIN

### 是否需要人工核查
否。

---

## [CASE-019] 动态分区写入未 DISTRIBUTE BY

**关联 KB**: KB-004, KB-040
**严重度**: medium

### 业务场景
将日增量数据按 dt 动态分区写入目标表，未加 DISTRIBUTE BY，产出大量小文件。

### 问题 SQL
```sql
INSERT OVERWRITE TABLE dwd_order PARTITION(dt)
SELECT order_id, user_id, amount, dt
FROM dwd_order_inc
WHERE dt >= '20261001' AND dt <= '20261031';
```

DDL（目标表）：
```sql
CREATE TABLE dwd_order (
  order_id string, user_id string, amount decimal(18,2)
) PARTITIONED BY (dt string) STORED AS ORC;
```

### 问题诊断
1. **KB-004** `PARTITION(dt)` 未指定分区值（动态分区），且 SELECT 末尾未加 `DISTRIBUTE BY dt`
2. **KB-040** 每个 Reducer 都会写入所有目标分区，小文件数 = Reducer 数 x 分区数

### 建议方向
- 在 SELECT 末尾加 `DISTRIBUTE BY dt`，让每个 Reducer 只写一个分区
- 若只有一个分区值，改为静态分区 `PARTITION(dt='20261010')`

### 是否需要人工核查
否。

---

## [CASE-020] 大 IN 列表致全表扫描

**关联 KB**: KB-035
**严重度**: medium

### 业务场景
按城市 ID 过滤订单数据，IN 列表包含 500+ 个字面值。

### 问题 SQL（节选）
```sql
SELECT order_id, amount
FROM dwd_order
WHERE dt = '20261010'
  AND city_id IN (
    110001, 110002, 110003, 110004, 110005,
    -- ... 共 500+ 个城市 ID
    440306
  );
```

### 问题诊断
1. **KB-035** IN 列表包含 500+ 个字面值，Hive 展开为 OR 链
2. 解析阶段耗时增加，优化器可能放弃部分优化
3. 若城市列表来自维度表，应改用 JOIN 替代

### 建议方向
- 将城市 ID 列表存入临时表 `dim_target_city`，用 LEFT SEMI JOIN 替代
- 或使用 `IN (SELECT city_id FROM dim_target_city)`

### 是否需要人工核查
否。

---

## [CASE-021] LATERAL VIEW EXPLODE 行数膨胀

**关联 KB**: KB-036
**严重度**: high

### 业务场景
80GB 用户行为表，LATERAL VIEW EXPLODE 展开行为数组，行数膨胀 10+ 倍。

### 问题 SQL
```sql
SELECT user_id, action_type, action_time
FROM dwd_user_behavior
LATERAL VIEW EXPLODE(action_list) t AS action_item
WHERE dt = '20261010';
```

DDL：
```sql
CREATE TABLE dwd_user_behavior (
  user_id string,
  action_list array<struct<type:string,time:string>>
) PARTITIONED BY (dt string) STORED AS ORC;
```

表容量 80GB，行数 5 亿，action_list 平均元素数 ~15。

### 问题诊断
1. **KB-036** EXPLODE 将每行展开为 ~15 行，5 亿行膨胀为 ~75 亿行
2. 膨胀后数据在后续处理（GROUP BY / JOIN / ORDER BY）中成本 15 倍增长
3. 若只需部分 action_type，应在 EXPLODE 前先过滤

### 建议方向
- 若只需判断是否包含某 type：用 `array_contains(action_list, ...)` 替代
- 若只需展开后过滤：先 WHERE 缩小范围再 EXPLODE
- 若需统计元素个数：用 `size(action_list)` 替代

### 是否需要人工核查
**是**。需抽样评估数组字段的平均元素个数。

---

## [CASE-022] JOIN 两侧字段类型不一致

**关联 KB**: KB-025
**严重度**: high

### 业务场景
订单表 user_id 为 string 类型，用户表 user_id 为 bigint 类型，JOIN 时隐式转换。

### 问题 SQL
```sql
SELECT a.order_id, b.user_name
FROM dwd_order a
JOIN dwd_user b ON a.user_id = b.user_id
WHERE a.dt = '20261010';
```

DDL：
```sql
CREATE TABLE dwd_order (order_id string, user_id string, ...) PARTITIONED BY (dt string);
CREATE TABLE dwd_user (user_id bigint, user_name string, ...);
```

### 问题诊断
1. **KB-025** `a.user_id` 为 string，`b.user_id` 为 bigint，隐式类型转换
2. 无法利用 sort-merge join / bucket map join 优化
3. string 与 bigint 隐式转换可能导致 `'123' = 123` 意外匹配或不匹配

### 建议方向
- 在 ETL 上游统一 user_id 字段类型
- 若无法改上游，在子查询中先显式转换类型再 JOIN

### 是否需要人工核查
否（DDL 即可判定）。

---

## [CASE-023] 同源表多次 INSERT 未合并

**关联 KB**: KB-037, KB-033
**严重度**: medium

### 业务场景
同一张 50GB 日志表被两个 INSERT 语句分别扫描，汇总到不同目标表。

### 问题 SQL
```sql
INSERT OVERWRITE TABLE rpt_user_active
SELECT user_id, COUNT(*) AS active_days
FROM dwd_user_log
WHERE dt >= '20261001' AND dt <= '20261031'
GROUP BY user_id;

INSERT OVERWRITE TABLE rpt_user_pay
SELECT user_id, SUM(amount) AS total_pay
FROM dwd_user_log
WHERE dt >= '20261001' AND dt <= '20261031' AND amount > 0
GROUP BY user_id;
```

### 问题诊断
1. **KB-037** 两个 INSERT 都扫描 `dwd_user_log`，50GB 表被扫描 2 次
2. **KB-033** 同源表重复扫描，可用 multi-insert 语法合并为一次扫描

### 建议方向
- 使用 multi-insert：`FROM dwd_user_log INSERT INTO rpt_user_active SELECT ... INSERT INTO rpt_user_pay SELECT ...`
- 一次扫描源表，多路写出

### 是否需要人工核查
否。

---

## [CASE-024] EXISTS 子查询应改 LEFT SEMI JOIN

**关联 KB**: KB-026, KB-023
**严重度**: medium

### 业务场景
查询"有下单行为的用户"，使用 EXISTS 子查询。

### 问题 SQL
```sql
SELECT user_id, user_name
FROM dwd_user
WHERE dt = '20261010'
  AND EXISTS (
    SELECT 1 FROM dwd_order
    WHERE dwd_order.user_id = dwd_user.user_id
      AND dwd_order.dt = '20261010'
  );
```

### 问题诊断
1. **KB-026** `EXISTS (SELECT ...)` 在 Hive 中效率低于 `LEFT SEMI JOIN`
2. **KB-023** 同类场景，IN/EXISTS 都应改为 LEFT SEMI JOIN
3. 只需要"是否存在匹配"，不需要子查询表的字段，完美适用 LEFT SEMI JOIN

### 建议方向
- 改为 `FROM dwd_user LEFT SEMI JOIN dwd_order ON dwd_user.user_id = dwd_order.user_id`
- 若 dwd_order 是小表可同时加 MAPJOIN hint

### 是否需要人工核查
否。

**关联 KB**: KB-034
**严重度**: medium

### 业务场景
5 层子查询嵌套，SELECT 列表中出现标量子查询。

### 问题 SQL（节选）
```sql
SELECT
  (SELECT name FROM dim_dept WHERE dept_id = a.dept_id) AS dept_name,
  (SELECT name FROM dim_city WHERE city_id = a.city_id) AS city_name,
  a.amount
FROM (
  SELECT dept_id, city_id, SUM(amount) AS amount
  FROM (
    SELECT dept_id, city_id, user_id, amount
    FROM (
      SELECT * FROM dwd_sales WHERE dt = '20261010'
    ) t1
    WHERE amount > 100
  ) t2
  GROUP BY dept_id, city_id
) a;
```

### 问题诊断
1. **KB-034** 子查询嵌套 5 层，优化器难以做谓词下推
2. **KB-034** SELECT 列表中出现标量子查询 `(SELECT name FROM ...)`，每行可能触发额外扫描
3. **KB-010** 出现 `SELECT *` 未做列裁剪

### 建议方向
- 用 CTE 扁平化多层子查询
- 标量子查询改为 LEFT JOIN
- 每层做好列裁剪和分区过滤

### 是否需要人工核查
否。

---

## [CASE-016] OR/AND 优先级致分区裁剪失效

**关联 KB**: KB-032, KB-011
**严重度**: critical

### 业务场景
查询某状态下的订单，OR 条件导致分区裁剪部分失效。

### 问题 SQL
```sql
SELECT order_id, status
FROM dwd_order
WHERE dt = '20261010' AND status = 'PAID'
  OR source = 'MOBILE';
```

DDL：
```sql
CREATE TABLE dwd_order (...) PARTITIONED BY (dt string) STORED AS ORC;
```

### 问题诊断
1. **KB-032** `AND > OR` 优先级导致语义等价于 `(dt='20261010' AND status='PAID') OR source='MOBILE'`
2. **KB-011** 第二个分支 `source='MOBILE'` 没有 `dt` 过滤，扫描全部历史分区
3. 业务意图大概率是 `dt='20261010' AND (status='PAID' OR source='MOBILE')`

### 建议方向
- 用括号明确优先级
- 确保 OR 的所有分支都包含分区过滤
- 与业务方确认真实意图

### 是否需要人工核查
**强烈建议**确认 OR 的业务语义。

---

## [CASE-017] 大表 GROUP BY 潜在倾斜

**关联 KB**: KB-001
**严重度**: high

### 业务场景
50GB 订单表按 user_id 做 GROUP BY 聚合，运行超 4 小时。

### 问题 SQL
```sql
SELECT user_id, COUNT(*) AS cnt, SUM(amount) AS total
FROM dwd_order
WHERE dt = '20261010'
GROUP BY user_id;
```

### 问题诊断
1. **KB-001** GROUP BY user_id 在 50GB 大表上存在倾斜风险
2. user_id 是高基数字段，部分热点用户可能产生大量数据集中到同一 Reducer
3. 仅凭 SQL 无法确认是否真倾斜，需标记为"潜在风险"

### 建议方向
- 建议人工抽样 `GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 10` 确认热点分布
- 若确认热点：使用两阶段聚合（先加随机后缀打散，再聚合去后缀）

### 是否需要人工核查
**是**。需抽样统计 GROUP BY 字段的 Top-N 分布。

---

## [CASE-018] 大表 JOIN 潜在倾斜

**关联 KB**: KB-003, KB-005
**严重度**: high

### 业务场景
两张大表（均超 50GB）按 user_id JOIN，运行超 6 小时。

### 问题 SQL
```sql
SELECT a.order_id, b.login_time
FROM dwd_order a
JOIN dwd_user_login b ON a.user_id = b.user_id
WHERE a.dt = '20261010' AND b.dt = '20261010';
```

### 问题诊断
1. **KB-003** 两张大表（均 >50GB）JOIN，存在 JOIN key 倾斜风险
2. **KB-005** user_id 字段可能存在大量 NULL 值，NULL 全部 hash 到同一 Reducer
3. 仅凭 SQL 无法确认是否真倾斜，需标记为"潜在风险"

### 建议方向
- 建议人工抽样两表 JOIN key 的 Top-N 分布和 NULL 占比
- 若确认倾斜：热点 key 单独 MapJoin，其余走普通 JOIN
- 若 NULL 占比高：在 ON 条件中对 NULL 做随机打散

### 是否需要人工核查
**是**。需抽样统计 JOIN Key 的分布与 NULL 占比。

---

**关联 KB**: KB-034, KB-022
**严重度**: medium

### 业务场景
历史遗留 SQL 使用逗号 JOIN，5 张表的过滤条件全部堆在 WHERE 中。

### 问题 SQL
```sql
SELECT r.order_id, t.sort_code, c.status
FROM dwd_order r,
     dim_product p,
     dim_consumer c,
     dim_relation m,
     dim_sort t
WHERE r.product_id = m.product_id
  AND m.consumer_id = p.consumer_id
  AND p.consumer_id = c.consumer_id
  AND r.sort_id = t.sort_id
  AND t.sort_code IN ('01','03')
  AND c.status < '9'
  AND r.dt = '20261010'
  AND p.dt = '20261010'
  AND c.dt = '20261010';
```

### 问题诊断
1. **KB-034** 老式逗号 JOIN，对优化器不友好，无法区分 JOIN 条件与过滤条件
2. **KB-022** 各表过滤条件全部在外层 WHERE，没有下推

### 建议方向
- 改为显式 `JOIN ... ON ...` 语法
- JOIN Key 放 ON，单表过滤放子查询 WHERE

### 是否需要人工核查
否。

---

