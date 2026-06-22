"""Quick smoke test: run CASE-1 against glm-5.1 to verify the local pipeline works."""
import sys, io, os, json
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(__file__))
from workflow_runner import run

sql = "select a.* from dwd_order a left join dim_user b on a.user_id=b.uid where a.dt='20250101';"
tables = [
    {"name": "dwd_order",
     "ddl": "CREATE TABLE dwd_order (order_id string, user_id string, amount decimal(18,2)) PARTITIONED BY (dt string) STORED AS ORC;",
     "size_bytes": 500*1024**3, "row_count": 5_000_000_000},
    {"name": "dim_user",
     "ddl": "CREATE TABLE dim_user (uid string, name string) STORED AS ORC;",
     "size_bytes": 50*1024**2, "row_count": 10_000_000},
]

result = run(sql, tables, model="glm-5.1")
print("=" * 70)
print("MODEL:", result["model"])
print("ok:", result["ok"])
print("--- stages ---")
print(json.dumps(result["stages"], ensure_ascii=False, indent=2))
print("--- json ---")
print(json.dumps(result["json"], ensure_ascii=False, indent=2)[:3000])
print("--- markdown (preview 800) ---")
print(result["markdown"][:800])
