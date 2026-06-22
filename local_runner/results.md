# Cross-model Hive SQL Agent Comparison

Models: glm-5.1, deepseek-v4-pro, kimi-k2.6, minimax-m3, doubao-seed-2.0-pro

Cases: 7

## Overall Ranking

| Model | Avg Score | Total Time(s) | All OK |
|-------|-----------|---------------|--------|
| deepseek-v4-pro | **1.0** | 340.1 | YES |
| kimi-k2.6 | **1.0** | 122.4 | YES |
| minimax-m3 | **1.0** | 230.0 | YES |
| doubao-seed-2.0-pro | **1.0** | 307.8 | YES |
| glm-5.1 | **0.82** | 196.9 | NO |

## Per-case detail

### CASE-1 big-small JOIN + select *
Expected CHK categories: `['sql_anti_pattern', 'join_strategy']`

| Model | Score | issues | Hit | Missing | Extra | Time(s) |
|-------|-------|--------|-----|---------|-------|---------|
| glm-5.1 | 1.0 | 2 | join_strategy,sql_anti_pattern | - | - | 29.5 |
| deepseek-v4-pro | 1.0 | 2 | join_strategy,sql_anti_pattern | - | - | 54.0 |
| kimi-k2.6 | 1.0 | 2 | join_strategy,sql_anti_pattern | - | - | 20.5 |
| minimax-m3 | 1.0 | 2 | join_strategy,sql_anti_pattern | - | - | 36.7 |
| doubao-seed-2.0-pro | 1.0 | 2 | join_strategy,sql_anti_pattern | - | - | 49.6 |

### CASE-2 missing partition filter
Expected CHK categories: `['partition_pruning']`

| Model | Score | issues | Hit | Missing | Extra | Time(s) |
|-------|-------|--------|-----|---------|-------|---------|
| glm-5.1 | 1.0 | 1 | partition_pruning | - | - | 23.0 |
| deepseek-v4-pro | 1.0 | 1 | partition_pruning | - | - | 36.7 |
| kimi-k2.6 | 1.0 | 1 | partition_pruning | - | - | 14.4 |
| minimax-m3 | 1.0 | 1 | partition_pruning | - | - | 30.1 |
| doubao-seed-2.0-pro | 1.0 | 1 | partition_pruning | - | - | 35.6 |

### CASE-3 multi count(distinct)
Expected CHK categories: `['aggregation']`

| Model | Score | issues | Hit | Missing | Extra | Time(s) |
|-------|-------|--------|-----|---------|-------|---------|
| glm-5.1 | 1.0 | 1 | aggregation | - | - | 26.3 |
| deepseek-v4-pro | 1.0 | 1 | aggregation | - | - | 51.6 |
| kimi-k2.6 | 1.0 | 1 | aggregation | - | - | 17.2 |
| minimax-m3 | 1.0 | 1 | aggregation | - | - | 41.3 |
| doubao-seed-2.0-pro | 1.0 | 1 | aggregation | - | - | 34.2 |

### CASE-4 ORDER BY no LIMIT + select *
Expected CHK categories: `['sql_anti_pattern', 'partition_pruning']`

| Model | Score | issues | Hit | Missing | Extra | Time(s) |
|-------|-------|--------|-----|---------|-------|---------|
| glm-5.1 | 0.0 | 0 | - | sql_anti_pattern,partition_pruning | - | 34.6 |
| deepseek-v4-pro | 1.0 | 3 | partition_pruning,sql_anti_pattern | - | - | 59.9 |
| kimi-k2.6 | 1.0 | 3 | partition_pruning,sql_anti_pattern | - | - | 21.5 |
| minimax-m3 | 1.0 | 3 | partition_pruning,sql_anti_pattern | - | - | 36.7 |
| doubao-seed-2.0-pro | 1.0 | 3 | partition_pruning,sql_anti_pattern | - | - | 64.5 |

### CASE-5 same table scanned 3 times
Expected CHK categories: `['subquery']`

| Model | Score | issues | Hit | Missing | Extra | Time(s) |
|-------|-------|--------|-----|---------|-------|---------|
| glm-5.1 | 0.75 | 2 | subquery | - | partition_pruning | 33.6 |
| deepseek-v4-pro | 1.0 | 1 | subquery | - | - | 66.9 |
| kimi-k2.6 | 1.0 | 1 | subquery | - | - | 17.9 |
| minimax-m3 | 1.0 | 1 | subquery | - | - | 36.4 |
| doubao-seed-2.0-pro | 1.0 | 1 | subquery | - | - | 47.4 |

### CASE-6 UNION should be UNION ALL
Expected CHK categories: `['sql_anti_pattern']`

| Model | Score | issues | Hit | Missing | Extra | Time(s) |
|-------|-------|--------|-----|---------|-------|---------|
| glm-5.1 | 1.0 | 1 | sql_anti_pattern | - | - | 26.2 |
| deepseek-v4-pro | 1.0 | 1 | sql_anti_pattern | - | - | 39.5 |
| kimi-k2.6 | 1.0 | 1 | sql_anti_pattern | - | - | 16.9 |
| minimax-m3 | 1.0 | 1 | sql_anti_pattern | - | - | 22.8 |
| doubao-seed-2.0-pro | 1.0 | 1 | sql_anti_pattern | - | - | 35.9 |

### CASE-7 clean SQL (fallback)
Expected CHK categories: `(none, fallback)`

| Model | Score | issues | Hit | Missing | Extra | Time(s) |
|-------|-------|--------|-----|---------|-------|---------|
| glm-5.1 | 1.0 | 1 | - | - | sql_anti_pattern | 23.7 |
| deepseek-v4-pro | 1.0 | 1 | - | - | sql_anti_pattern | 31.5 |
| kimi-k2.6 | 1.0 | 1 | - | - | sql_anti_pattern | 14.0 |
| minimax-m3 | 1.0 | 1 | - | - | sql_anti_pattern | 26.0 |
| doubao-seed-2.0-pro | 1.0 | 1 | - | - | sql_anti_pattern | 40.6 |
