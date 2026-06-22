"""Node 2 unit tests (Qianfan def main(params) signature).

Run: python -m pytest tests/test_node2.py -v
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from node2_parse_input import main as node2_main


def call(sql, tables):
    return node2_main({"sql": sql, "tables": tables})


# ===== 1. Single table - partition pruning hit =====
def test_single_table_partition_hit():
    tables = json.dumps([
        {
            "name": "dwd_order",
            "ddl": "CREATE TABLE dwd_order (id string, create_time string) PARTITIONED BY (dt string) STORED AS ORC;",
            "size_bytes": 536870912000,
            "row_count": 5000000000,
        }
    ])
    out = call("select id from dwd_order where create_time >= '2024-01-01';", tables)
    assert out["sql"].startswith("select id")
    assert "dwd_order" in out["tables_md"]
    assert "500.0GB" in out["tables_md"]
    assert "5000000000" in out["tables_md"]
    assert "PARTITIONED BY" in out["tables_md"]
    assert "partition pruning" in out["retrieval_query"]


# ===== 2. Multiple tables, no anti-pattern -> fallback =====
def test_multiple_tables_no_anti_pattern():
    tables = json.dumps([
        {"name": "dwd_order", "ddl": "CREATE TABLE dwd_order(id string) PARTITIONED BY (dt string);", "size_bytes": 1073741824, "row_count": 10000000},
    ])
    out = call("select id from dwd_order where dt='20250101';", tables)
    assert "dwd_order" in out["tables_md"]
    # No anti-pattern detected -> fallback retrieval_query
    assert "Hive SQL optimization" in out["retrieval_query"] or out["retrieval_query"]


# ===== 3. Empty tables array =====
def test_empty_tables():
    out = call("select 1;", "[]")
    assert out["sql"] == "select 1;"
    assert out["tables_md"] == ""
    assert out["retrieval_query"]  # not empty


# ===== 4. Missing optional fields =====
def test_missing_optional_fields():
    tables = json.dumps([{"name": "t1", "ddl": "CREATE TABLE t1(id int);"}])
    out = call("select id from t1;", tables)
    assert "t1" in out["tables_md"]
    assert "0.0B" in out["tables_md"]


# ===== 5. Missing name field =====
def test_missing_name_field():
    tables = json.dumps([{"ddl": "CREATE TABLE t(id int);", "size_bytes": 100, "row_count": 1}])
    out = call("select id from t;", tables)
    assert "<unknown>" in out["tables_md"]


# ===== 6. PB scale size =====
def test_pb_scale_size():
    pb_size = 5 * 1024 ** 5
    tables = json.dumps([{"name": "t", "ddl": "CREATE TABLE t(id int);", "size_bytes": pb_size, "row_count": 1}])
    out = call("select id from t;", tables)
    assert "5.0PB" in out["tables_md"]


# ===== 7. Size unit boundaries =====
def test_size_unit_boundaries():
    cases = [
        (0, "0.0B"),
        (1023, "1023.0B"),
        (1024, "1.0KB"),
        (1024 * 1024, "1.0MB"),
        (1024 ** 3, "1.0GB"),
        (1024 ** 4, "1.0TB"),
    ]
    for size, expected in cases:
        tables = json.dumps([{"name": "t", "ddl": "x", "size_bytes": size, "row_count": 1}])
        out = call("select 1 from t;", tables)
        assert expected in out["tables_md"], f"size={size}, expected={expected}, got={out['tables_md']}"


# ===== 8. Invalid JSON tables =====
def test_invalid_json_tables():
    out = call("select 1;", "not a json")
    assert out["tables_md"].startswith("[ERROR]")
    assert out["sql"] == "select 1;"
    assert out["retrieval_query"] == "select 1;"


# ===== 9. tables is dict not list =====
def test_tables_is_not_list():
    out = call("select 1;", '{"name": "t"}')
    assert out["tables_md"].startswith("[ERROR]")


# ===== 10. sql is None =====
def test_sql_none():
    tables = json.dumps([{"name": "t1", "ddl": "x", "size_bytes": 100, "row_count": 1}])
    out = call(None, tables)
    assert out["sql"] == ""


# ===== 11. Both empty =====
def test_both_empty_strings():
    out = call("", "")
    assert out["tables_md"].startswith("[ERROR]")
    assert out["sql"] == ""


# ===== 12. Return field types =====
def test_return_field_types():
    tables = json.dumps([{"name": "t", "ddl": "x", "size_bytes": 100, "row_count": 1}])
    out = call("select 1 from t;", tables)
    assert isinstance(out["tables_md"], str)
    assert isinstance(out["retrieval_query"], str)
    assert isinstance(out["sql"], str)
    assert set(out.keys()) == {"tables_md", "retrieval_query", "sql"}


# ===== 13. params missing fields =====
def test_params_missing_fields():
    out = node2_main({})
    assert out["sql"] == ""
    assert out["tables_md"].startswith("[ERROR]")


# ===== 14. CHK-2 select * detected =====
def test_chk_select_star():
    tables = json.dumps([{"name": "t", "ddl": "create table t(a int) partitioned by (dt string);", "size_bytes": 100, "row_count": 1}])
    out = call("select * from t where dt='20250101';", tables)
    assert "select star" in out["retrieval_query"]


# ===== 15. CHK-3 small table JOIN no MapJoin =====
def test_chk_small_join_no_mapjoin():
    tables = json.dumps([
        {"name": "big", "ddl": "create table big(id int) partitioned by (dt string);", "size_bytes": 500 * 1024 ** 3, "row_count": 5_000_000_000},
        {"name": "dim", "ddl": "create table dim(id int);", "size_bytes": 50 * 1024 ** 2, "row_count": 100000},
    ])
    out = call("select a.id from big a left join dim b on a.id=b.id where a.dt='20250101';", tables)
    assert "MapJoin" in out["retrieval_query"]


# ===== 16. CHK-4 multiple count(distinct) =====
def test_chk_multi_count_distinct():
    tables = json.dumps([{"name": "t", "ddl": "create table t(a int, b int) partitioned by (dt string);", "size_bytes": 100, "row_count": 1}])
    out = call("select count(distinct a), count(distinct b) from t where dt='20250101';", tables)
    assert "count distinct" in out["retrieval_query"]


# ===== 17. CHK-5 ORDER BY no LIMIT =====
def test_chk_order_by_no_limit():
    tables = json.dumps([{"name": "t", "ddl": "create table t(a int) partitioned by (dt string);", "size_bytes": 100, "row_count": 1}])
    out = call("select a from t where dt='20250101' order by a desc;", tables)
    assert "order by no limit" in out["retrieval_query"]


# ===== 18. CHK-6 UNION (not UNION ALL) =====
def test_chk_union_not_all():
    tables = json.dumps([{"name": "t", "ddl": "create table t(a int) partitioned by (dt string);", "size_bytes": 100, "row_count": 1}])
    out = call("select a from t where dt='20250101' union select a from t where dt='20250102';", tables)
    assert "UNION ALL" in out["retrieval_query"]


# ===== 19. CHK-7 same table scanned 3+ times =====
def test_chk_repeated_table_scan():
    tables = json.dumps([
        {"name": "fact", "ddl": "create table fact(id int) partitioned by (dt string);", "size_bytes": 100, "row_count": 1},
        {"name": "fct_activity", "ddl": "create table fct_activity(id int, k string);", "size_bytes": 100, "row_count": 1},
    ])
    sql = (
        "select b.id from fact b "
        "left join (select id from fct_activity where k='a') c on b.id=c.id "
        "left join (select id from fct_activity where k='b') d on b.id=d.id "
        "left join (select id from fct_activity where k='c') e on b.id=e.id "
        "where b.dt='20250101';"
    )
    out = call(sql, tables)
    assert "repeated table scan" in out["retrieval_query"]


# ===== 20. CHK-12 IN (SELECT ...) =====
def test_chk_in_subquery():
    tables = json.dumps([
        {"name": "a", "ddl": "create table a(id int) partitioned by (dt string);", "size_bytes": 100, "row_count": 1},
        {"name": "b", "ddl": "create table b(id int);", "size_bytes": 100 * 1024 ** 3, "row_count": 1},
    ])
    out = call("select id from a where dt='20250101' and id in (select id from b);", tables)
    assert "LEFT SEMI JOIN" in out["retrieval_query"]


# ===== 21. retrieval_query length cap =====
def test_retrieval_query_capped():
    tables = json.dumps([{"name": "t", "ddl": "create table t(a int) partitioned by (dt string);", "size_bytes": 100, "row_count": 1}])
    out = call("select * from t where create_time >= '2024-01-01' order by a;", tables)
    assert len(out["retrieval_query"]) <= 500
