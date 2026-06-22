"""节点 5 测试用例：JSON 解析（千帆 def main(params) 风格）

签名：main(params: dict) -> dict
入参 key：output
出参：ok (bool), json (dict|Any), markdown (str)

运行：python -m pytest tests/test_node5.py -v
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from node5_parse_json import main as node5_main


def call(raw):
    return node5_main({"output": raw})


# ===== 1. 正常 JSON =====
def test_plain_json():
    payload = {
        "summary": "测试",
        "severity": "high",
        "issues": [{"id": "ISSUE-001", "title": "t"}],
        "needs_human_check": ["核查 key 分布"],
        "markdown_report": "## 总结\n测试内容",
    }
    raw = json.dumps(payload, ensure_ascii=False)
    out = call(raw)
    assert out["ok"] is True
    assert out["json"]["summary"] == "测试"
    assert out["json"]["issues"][0]["id"] == "ISSUE-001"
    assert out["markdown"] == "## 总结\n测试内容"


# ===== 2. ```json 包裹 =====
def test_json_code_fence():
    payload = {"summary": "ok", "markdown_report": "# Hi"}
    raw = "这是模型的多余前言\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```\n后缀"
    out = call(raw)
    assert out["ok"] is True
    assert out["json"]["summary"] == "ok"
    assert out["markdown"] == "# Hi"


# ===== 3. markdown_report 优先 =====
def test_markdown_field_fallback():
    raw = json.dumps({"summary": "x", "markdown": "fallback md"})
    out = call(raw)
    assert out["ok"] is True
    assert out["markdown"] == "fallback md"


# ===== 4. 没有 markdown_report 时基于 JSON 字段重建 =====
def test_rebuild_markdown_from_fields():
    raw = json.dumps({
        "summary": "S",
        "severity": "high",
        "issues": [{"id": "ISSUE-001", "severity": "high", "category": "x", "title": "T",
                    "evidence": "e", "root_cause": "r", "recommendation": "r2", "expected_gain": "3x"}],
        "needs_human_check": ["核查 a"],
    })
    out = call(raw)
    assert out["ok"] is True
    assert "## 总结" in out["markdown"]
    assert "ISSUE-001" in out["markdown"]
    assert "核查 a" in out["markdown"]


# ===== 5. 非法 JSON 且非 markdown =====
def test_invalid_non_markdown():
    out = call("this is not json {[}")
    assert out["ok"] is False
    assert "error" in out["json"]
    assert "raw" in out["json"]
    assert "JSON 解析失败" in out["markdown"]


# ===== 6. 空字符串 =====
def test_empty_string():
    out = call("")
    assert out["ok"] is False


# ===== 7. None 输入 =====
def test_none_input():
    out = call(None)
    assert out["ok"] is False
    assert isinstance(out["json"], dict)
    assert isinstance(out["markdown"], str)


# ===== 8. 中文不转义 =====
def test_chinese_not_escaped():
    payload = {"summary": "数据倾斜风险", "markdown_report": "## 中文报告"}
    raw = json.dumps(payload, ensure_ascii=False)
    out = call(raw)
    assert out["json"]["summary"] == "数据倾斜风险"
    assert "中文报告" in out["markdown"]


# ===== 9. 出参类型 =====
def test_output_types():
    raw = json.dumps({"summary": "x", "markdown_report": "y"})
    out = call(raw)
    assert isinstance(out["ok"], bool)
    assert isinstance(out["json"], dict)
    assert isinstance(out["markdown"], str)
    assert set(out.keys()) == {"ok", "json", "markdown"}


# ===== 10. raw 截断 =====
def test_raw_truncation_on_failure():
    huge = "x" * 5000 + " not json"
    out = call(huge)
    assert out["ok"] is False
    assert len(out["json"]["raw"]) <= 2000


# ===== 11. 嵌套结构 =====
def test_nested_structure():
    payload = {
        "summary": "x",
        "issues": [{"id": "ISSUE-001", "evidence": "...", "needs_human_check": ["c1", "c2"]}],
        "markdown_report": "report",
    }
    raw = json.dumps(payload, ensure_ascii=False)
    out = call(raw)
    assert out["ok"] is True
    assert out["json"]["issues"][0]["needs_human_check"] == ["c1", "c2"]


# ===== 12. ```json 包裹 + 啰嗦前言 =====
def test_json_fence_with_noise():
    raw = """好的，我来分析一下。

根据您的描述，问题主要在...

```json
{"summary": "诊断完成", "markdown_report": "# Report"}
```

希望以上分析对您有帮助！"""
    out = call(raw)
    assert out["ok"] is True
    assert out["json"]["summary"] == "诊断完成"


# ===== 13. output 前缀（千帆有时回 "output{...}"）=====
def test_output_prefix():
    raw = "output" + json.dumps({"summary": "p", "markdown_report": "m"}, ensure_ascii=False)
    out = call(raw)
    assert out["ok"] is True
    assert out["json"]["summary"] == "p"


# ===== 14. LLM 完全输出 Markdown 而非 JSON：透传降级 =====
def test_pure_markdown_passthrough():
    md = "# 总结\n该 SQL 存在多个大表 Join 操作。\n## 问题列表\n### ISSUE-001: xxx\n- **证据**: ..."
    out = call(md)
    assert out["ok"] is True
    assert out["json"]["markdown_report"] == md
    assert out["json"]["_warning"]
    assert out["markdown"] == md


# ===== 15. 同时含啰嗦前言 + JSON：仍能解析 =====
def test_prefix_text_then_json():
    raw = "好的，结果如下：\n" + json.dumps({"summary": "S", "markdown_report": "M"}, ensure_ascii=False)
    out = call(raw)
    assert out["ok"] is True
    assert out["json"]["summary"] == "S"
