"""Node 5: JSON parsing (Qianfan code node - Python).

Qianfan requires the function signature to be `def main(params):`,
all inputs are passed via the `params` dict.

Inputs (must match console "input definition" exactly):
  output : String - raw output of LLM node 4

Outputs (must match console "output definition" exactly, case sensitive):
  ok       : Boolean
  json     : Any      - parsed structured result (dict)
  markdown : String   - human-readable Markdown report
"""
import json
import re


def _try_parse_json(txt):
    if not txt:
        return None
    candidates = [txt.strip()]
    m = re.search(r"```json\s*(.+?)\s*```", txt, re.S)
    if m:
        candidates.append(m.group(1).strip())
    m = re.search(r"```\s*(\{.+?\})\s*```", txt, re.S)
    if m:
        candidates.append(m.group(1).strip())
    if "{" in txt and "}" in txt:
        candidates.append(txt[txt.find("{"): txt.rfind("}") + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return None


def _markdown_from_json(data):
    md = data.get("markdown_report") or data.get("markdown") or data.get("markdown_output")
    if md:
        return md

    parts = []
    if data.get("summary"):
        parts.append(u"## \u603b\u7ed3\n\n" + str(data["summary"]))
    if data.get("severity"):
        parts.append(u"**\u4e25\u91cd\u7b49\u7ea7**\uff1a" + str(data["severity"]))
    if data.get("estimated_speedup"):
        parts.append(u"**\u9884\u4f30\u6536\u76ca**\uff1a" + str(data["estimated_speedup"]))

    issues = data.get("issues") or []
    if issues:
        parts.append(u"## \u95ee\u9898\u5217\u8868")
        for i, iss in enumerate(issues, 1):
            parts.append(
                u"### " + str(iss.get("id", "ISSUE-" + str(i).zfill(3)))
                + u" [" + str(iss.get("severity", "")) + u"] "
                + str(iss.get("category", "")) + u": "
                + str(iss.get("title", "")) + u"\n"
                + u"- **\u8bc1\u636e**\uff1a" + str(iss.get("evidence", "")) + u"\n"
                + u"- **\u6839\u56e0**\uff1a" + str(iss.get("root_cause", "")) + u"\n"
                + u"- **\u5efa\u8bae**\uff1a" + str(iss.get("recommendation", "")) + u"\n"
                + u"- **\u9884\u4f30\u6536\u76ca**\uff1a" + str(iss.get("expected_gain", ""))
            )

    needs = data.get("needs_human_check") or []
    if needs:
        parts.append(u"## \u9700\u4eba\u5de5\u6838\u67e5\u9879")
        for n in needs:
            parts.append(u"- " + str(n))

    return "\n\n".join(parts) if parts else ""


def main(params):
    raw = params.get("output", "") or ""
    txt = str(raw).strip()

    if txt.startswith("output{") or txt.startswith("output {"):
        txt = txt[len("output"):].lstrip()

    data = _try_parse_json(txt)

    if isinstance(data, dict):
        return {
            "ok": True,
            "json": data,
            "markdown": _markdown_from_json(data),
        }

    looks_like_md = txt.startswith("#") or "\n## " in txt or "\n### " in txt
    if looks_like_md:
        return {
            "ok": True,
            "json": {
                "summary": "",
                "severity": "",
                "estimated_speedup": "",
                "issues": [],
                "needs_human_check": [],
                "markdown_report": txt,
                "_warning": "LLM did not output JSON per schema, passed through as Markdown",
            },
            "markdown": txt,
        }

    return {
        "ok": False,
        "json": {
            "error": "JSON parse failed and not markdown",
            "raw": txt[:2000],
        },
        "markdown": u"## JSON \u89e3\u6790\u5931\u8d25\n\n```\n" + txt[:2000] + u"\n```",
    }
