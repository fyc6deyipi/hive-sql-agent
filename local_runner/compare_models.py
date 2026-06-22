"""Cross-model comparison runner.

For each (model, case) pair: run the local workflow, score how well the LLM
identified the expected CHKs. Write a comparison table to results.md.

Usage:
  python local_runner/compare_models.py
  python local_runner/compare_models.py glm-5.1 deepseek-v4-pro
"""
import sys
import os
import io
import json
import time
import traceback

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(__file__))
from workflow_runner import run

from compare_cases import CASES, DEFAULT_MODELS


def score_case(result: dict, expected: list) -> dict:
    if not result["ok"]:
        return {"hit_categories": [], "missing": expected, "extra": [],
                "score": 0.0, "issue_count": 0}
    issues = (result["json"] or {}).get("issues") or []
    got_categories = list({(i.get("category") or "") for i in issues})
    expected_set = set(expected)
    got_set = set(got_categories)
    hit = sorted(expected_set & got_set)
    missing = sorted(expected_set - got_set)
    extra = sorted(got_set - expected_set)

    if not expected:
        sev = (result["json"] or {}).get("severity", "")
        is_low = sev == "low"
        small = len(issues) <= 1
        score = 1.0 if (is_low and small) else max(0.0, 1.0 - 0.3 * len(issues))
    else:
        recall = len(hit) / max(1, len(expected_set))
        precision = len(hit) / max(1, len(got_set)) if got_set else 0.0
        score = round((recall + precision) / 2, 2)

    return {
        "hit_categories": hit,
        "missing": missing,
        "extra": extra,
        "score": score,
        "issue_count": len(issues),
    }


def main():
    models = sys.argv[1:] or DEFAULT_MODELS
    out_dir = os.path.dirname(__file__)
    md_path = os.path.join(out_dir, "results.md")
    json_path = os.path.join(out_dir, "results.json")

    summary = {m: [] for m in models}
    full_data = []

    for model in models:
        print()
        print("#" * 70)
        print(f"# MODEL: {model}")
        print("#" * 70)
        for case in CASES:
            print(f"\n>>> {model} | {case['label']}")
            try:
                result = run(case["sql"], case["tables"], model=model,
                             temperature=0.1, max_tokens=4096)
                sc = score_case(result, case["expected_chks"])
                ok = result["ok"]
                err = result.get("error")
                print(f"    elapsed={result['stages']['node4_elapsed_s']}s "
                      f"ok={ok} score={sc['score']} hit={sc['hit_categories']} "
                      f"miss={sc['missing']} extra={sc['extra']}")
                summary[model].append({
                    "case_id": case["id"], "label": case["label"],
                    "score": sc["score"], "issue_count": sc["issue_count"],
                    "hit": sc["hit_categories"], "missing": sc["missing"],
                    "extra": sc["extra"],
                    "elapsed": result["stages"]["node4_elapsed_s"],
                    "ok": ok, "error": err,
                })
                full_data.append({
                    "model": model, "case_id": case["id"],
                    "case_label": case["label"], "score": sc,
                    "result_json": result["json"],
                    "result_markdown": result["markdown"],
                    "stages": result["stages"],
                })
            except Exception as e:
                print(f"    EXCEPTION: {e}")
                traceback.print_exc()
                summary[model].append({
                    "case_id": case["id"], "label": case["label"],
                    "score": 0.0, "issue_count": 0,
                    "hit": [], "missing": case["expected_chks"], "extra": [],
                    "elapsed": -1, "ok": False, "error": str(e),
                })
            time.sleep(1)

    _write_report(models, summary, full_data, md_path, json_path)
    print(f"\n\nResults written to:\n  {md_path}\n  {json_path}")


def _write_report(models, summary, full_data, md_path, json_path):
    lines = []
    lines.append("# Cross-model Hive SQL Agent Comparison\n")
    lines.append(f"Models: {', '.join(models)}\n")
    lines.append(f"Cases: {len(CASES)}\n")

    # Ranking
    lines.append("## Overall Ranking\n")
    lines.append("| Model | Avg Score | Total Time(s) | All OK |")
    lines.append("|-------|-----------|---------------|--------|")
    rank = []
    for m in models:
        arr = summary[m]
        if not arr:
            continue
        avg = round(sum(x["score"] for x in arr) / len(arr), 2)
        total_t = round(sum(max(x["elapsed"], 0) for x in arr), 1)
        all_ok = all(x["ok"] for x in arr)
        rank.append((m, avg, total_t, all_ok))
    rank.sort(key=lambda x: -x[1])
    for m, avg, t, ok in rank:
        lines.append(f"| {m} | **{avg}** | {t} | {'YES' if ok else 'NO'} |")
    lines.append("")

    # Per-case breakdown
    lines.append("## Per-case detail\n")
    for case in CASES:
        lines.append(f"### {case['label']}")
        lines.append(f"Expected CHK categories: `{case['expected_chks'] or '(none, fallback)'}`\n")
        lines.append("| Model | Score | issues | Hit | Missing | Extra | Time(s) |")
        lines.append("|-------|-------|--------|-----|---------|-------|---------|")
        for m in models:
            r = next((x for x in summary[m] if x["case_id"] == case["id"]), None)
            if not r:
                continue
            lines.append(
                f"| {m} | {r['score']} | {r['issue_count']} | "
                f"{','.join(r['hit']) or '-'} | "
                f"{','.join(r['missing']) or '-'} | "
                f"{','.join(r['extra']) or '-'} | "
                f"{r['elapsed']} |"
            )
        lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(full_data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
