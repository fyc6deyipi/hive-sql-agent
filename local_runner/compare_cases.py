"""Test cases shared by compare_models runner.

Each case has:
  id, label, sql, tables, expected_chks (list of category names)

The category vocabulary matches system_prompt.md "category" enum:
  partition_pruning | join_strategy | aggregation | sql_anti_pattern |
  storage_format | subquery | window_function | data_skew
"""

CASES = [
    {
        "id": 1, "label": "CASE-1 big-small JOIN + select *",
        "sql": "select a.* from dwd_order a left join dim_user b on a.user_id=b.uid where a.dt='20250101';",
        "tables": [
            {"name": "dwd_order",
             "ddl": "CREATE TABLE dwd_order (order_id string, user_id string, amount decimal(18,2)) PARTITIONED BY (dt string) STORED AS ORC;",
             "size_bytes": 500 * 1024 ** 3, "row_count": 5_000_000_000},
            {"name": "dim_user",
             "ddl": "CREATE TABLE dim_user (uid string, name string) STORED AS ORC;",
             "size_bytes": 50 * 1024 ** 2, "row_count": 10_000_000},
        ],
        "expected_chks": ["sql_anti_pattern", "join_strategy"],
    },
    {
        "id": 2, "label": "CASE-2 missing partition filter",
        "sql": "select order_id, amount from dwd_order where create_time >= '2024-01-01';",
        "tables": [
            {"name": "dwd_order",
             "ddl": "CREATE TABLE dwd_order (order_id string, amount decimal(18,2), create_time string) PARTITIONED BY (dt string) STORED AS ORC;",
             "size_bytes": 500 * 1024 ** 3, "row_count": 5_000_000_000},
        ],
        "expected_chks": ["partition_pruning"],
    },
    {
        "id": 3, "label": "CASE-3 multi count(distinct)",
        "sql": "select count(distinct user_id) as uv, count(distinct order_id) as order_cnt from dwd_order where dt='20250101';",
        "tables": [
            {"name": "dwd_order",
             "ddl": "CREATE TABLE dwd_order (order_id string, user_id string) PARTITIONED BY (dt string) STORED AS ORC;",
             "size_bytes": 100 * 1024 ** 3, "row_count": 100_000_000},
        ],
        "expected_chks": ["aggregation"],
    },
    {
        "id": 4, "label": "CASE-4 ORDER BY no LIMIT + select *",
        "sql": "select * from dwd_order order by create_time desc;",
        "tables": [
            {"name": "dwd_order",
             "ddl": "CREATE TABLE dwd_order (order_id string, create_time string) PARTITIONED BY (dt string) STORED AS ORC;",
             "size_bytes": 500 * 1024 ** 3, "row_count": 5_000_000_000},
        ],
        "expected_chks": ["sql_anti_pattern", "partition_pruning"],
    },
    {
        "id": 5, "label": "CASE-5 same table scanned 3 times",
        "sql": (
            "select b.process_id\n"
            "from fact_order b\n"
            "left join (select process_id from FCT_ACTIVITY where link_define_nm='answer-plan') c "
            "on b.process_id=c.process_id\n"
            "left join (select process_id from FCT_ACTIVITY where link_define_nm='intake') d "
            "on b.process_id=d.process_id\n"
            "left join (select process_id from FCT_ACTIVITY where link_define_nm='design-doc') e "
            "on b.process_id=e.process_id\n"
            "where b.dt='20250101';"
        ),
        "tables": [
            {"name": "fact_order",
             "ddl": "CREATE TABLE fact_order (process_id string) PARTITIONED BY (dt string) STORED AS ORC;",
             "size_bytes": 100 * 1024 ** 3, "row_count": 100_000_000},
            {"name": "FCT_ACTIVITY",
             "ddl": "CREATE TABLE FCT_ACTIVITY (process_id string, link_define_nm string, end_tm string) STORED AS ORC;",
             "size_bytes": 50 * 1024 ** 3, "row_count": 50_000_000},
        ],
        "expected_chks": ["subquery"],
    },
    {
        "id": 6, "label": "CASE-6 UNION should be UNION ALL",
        "sql": "select uid from dwd_user_active where dt='20250101' union select uid from dwd_user_active where dt='20250102';",
        "tables": [
            {"name": "dwd_user_active",
             "ddl": "CREATE TABLE dwd_user_active (uid string) PARTITIONED BY (dt string) STORED AS ORC;",
             "size_bytes": 10 * 1024 ** 3, "row_count": 10_000_000},
        ],
        "expected_chks": ["sql_anti_pattern"],
    },
    {
        "id": 7, "label": "CASE-7 clean SQL (fallback)",
        "sql": "select order_id, amount from dwd_order where dt='20250101';",
        "tables": [
            {"name": "dwd_order",
             "ddl": "CREATE TABLE dwd_order (order_id string, amount decimal(18,2)) PARTITIONED BY (dt string) STORED AS ORC;",
             "size_bytes": 10 * 1024 ** 3, "row_count": 10_000_000},
        ],
        "expected_chks": [],
    },
    {
        "id": 8, "label": "CASE-8 partition field wrapped by function",
        "sql": "select order_id, amount from dwd_order where substr(dt, 1, 6) = '202610';",
        "tables": [
            {"name": "dwd_order",
             "ddl": "CREATE TABLE dwd_order (order_id string, amount decimal(18,2)) PARTITIONED BY (dt string) STORED AS ORC;",
             "size_bytes": 500 * 1024 ** 3, "row_count": 5_000_000_000},
        ],
        "expected_chks": ["partition_pruning"],
    },
    {
        "id": 9, "label": "CASE-9 predicate not pushed down",
        "sql": (
            "select f.order_id, a.region_name, b.category_name "
            "from dwd_order_fact f "
            "left join dim_region a on f.region_id = a.region_id "
            "left join dim_category b on f.category_id = b.category_id "
            "where f.dt = '20261010' and a.is_active = 1 and b.level = 1;"
        ),
        "tables": [
            {"name": "dwd_order_fact",
             "ddl": "CREATE TABLE dwd_order_fact (order_id string, region_id string, category_id string) PARTITIONED BY (dt string) STORED AS ORC;",
             "size_bytes": 200 * 1024 ** 3, "row_count": 2_000_000_000},
            {"name": "dim_region",
             "ddl": "CREATE TABLE dim_region (region_id string, region_name string, is_active int) STORED AS ORC;",
             "size_bytes": 5 * 1024 ** 2, "row_count": 500},
            {"name": "dim_category",
             "ddl": "CREATE TABLE dim_category (category_id string, category_name string, level int) STORED AS ORC;",
             "size_bytes": 1 * 1024 ** 2, "row_count": 200},
        ],
        "expected_chks": ["join_strategy"],
    },
    {
        "id": 10, "label": "CASE-10 comma JOIN",
        "sql": (
            "select r.order_id, t.sort_code "
            "from dwd_order r, dim_product p, dim_sort t "
            "where r.product_id = p.product_id and r.sort_id = t.sort_id "
            "and r.dt = '20261010';"
        ),
        "tables": [
            {"name": "dwd_order",
             "ddl": "CREATE TABLE dwd_order (order_id string, product_id string, sort_id string) PARTITIONED BY (dt string) STORED AS ORC;",
             "size_bytes": 100 * 1024 ** 3, "row_count": 1_000_000_000},
            {"name": "dim_product",
             "ddl": "CREATE TABLE dim_product (product_id string, name string) STORED AS ORC;",
             "size_bytes": 50 * 1024 ** 2, "row_count": 10_000},
            {"name": "dim_sort",
             "ddl": "CREATE TABLE dim_sort (sort_id string, sort_code string) STORED AS ORC;",
             "size_bytes": 1 * 1024 ** 2, "row_count": 100},
        ],
        "expected_chks": ["sql_anti_pattern"],
    },
    {
        "id": 11, "label": "CASE-11 OR/AND precedence error",
        "sql": "select order_id, status from dwd_order where dt = '20261010' and status = 'PAID' or source = 'MOBILE';",
        "tables": [
            {"name": "dwd_order",
             "ddl": "CREATE TABLE dwd_order (order_id string, status string, source string) PARTITIONED BY (dt string) STORED AS ORC;",
             "size_bytes": 500 * 1024 ** 3, "row_count": 5_000_000_000},
        ],
        "expected_chks": ["sql_anti_pattern", "partition_pruning"],
    },
    {
        "id": 12, "label": "CASE-12 GROUP BY potential skew",
        "sql": "select user_id, count(*) as cnt, sum(amount) as total from dwd_order where dt='20261010' group by user_id;",
        "tables": [
            {"name": "dwd_order",
             "ddl": "CREATE TABLE dwd_order (order_id string, user_id string, amount decimal(18,2)) PARTITIONED BY (dt string) STORED AS ORC;",
             "size_bytes": 50 * 1024 ** 3, "row_count": 500_000_000},
        ],
        "expected_chks": ["data_skew"],
    },
    {
        "id": 13, "label": "CASE-13 JOIN type mismatch (string vs bigint)",
        "sql": "select a.order_id, b.user_name from dwd_order a join dwd_user b on a.user_id = b.user_id where a.dt='20261010';",
        "tables": [
            {"name": "dwd_order",
             "ddl": "CREATE TABLE dwd_order (order_id string, user_id string) PARTITIONED BY (dt string) STORED AS ORC;",
             "size_bytes": 100 * 1024 ** 3, "row_count": 1_000_000_000},
            {"name": "dwd_user",
             "ddl": "CREATE TABLE dwd_user (user_id bigint, user_name string) STORED AS ORC;",
             "size_bytes": 5 * 1024 ** 3, "row_count": 50_000_000},
        ],
        "expected_chks": ["join_strategy"],
    },
    {
        "id": 14, "label": "CASE-14 EXISTS subquery",
        "sql": "select user_id, user_name from dwd_user where dt='20261010' and exists (select 1 from dwd_order where dwd_order.user_id = dwd_user.user_id and dwd_order.dt='20261010');",
        "tables": [
            {"name": "dwd_user",
             "ddl": "CREATE TABLE dwd_user (user_id string, user_name string) PARTITIONED BY (dt string) STORED AS ORC;",
             "size_bytes": 5 * 1024 ** 3, "row_count": 50_000_000},
            {"name": "dwd_order",
             "ddl": "CREATE TABLE dwd_order (order_id string, user_id string) PARTITIONED BY (dt string) STORED AS ORC;",
             "size_bytes": 100 * 1024 ** 3, "row_count": 1_000_000_000},
        ],
        "expected_chks": ["subquery"],
    },
]

DEFAULT_MODELS = [
    "kimi-k2.6",
    "deepseek-v4-pro",
    "glm-5.1",
]
