"""Local KB retrieval (Node 3 emulation).

Loads hive_sql_optimization_kb.md once, splits into chunks (each starts at H2/H3 heading),
returns top-K chunks ranked by simple keyword overlap with the retrieval_query.
This emulates the Qianfan KB retrieval node so the local runner can run end-to-end.
"""
import os
import re

_KB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hive_sql_optimization_kb.md")
_CHUNKS_CACHE = None


def _load_chunks():
    global _CHUNKS_CACHE
    if _CHUNKS_CACHE is not None:
        return _CHUNKS_CACHE
    if not os.path.exists(_KB_PATH):
        _CHUNKS_CACHE = []
        return _CHUNKS_CACHE

    with open(_KB_PATH, "r", encoding="utf-8") as f:
        text = f.read()

    # Split by every "## " or "### " heading to get fine-grained chunks.
    parts = re.split(r"(?m)^(##\s.+|###\s.+)$", text)
    chunks = []
    cur_title = ""
    cur_body = []
    for seg in parts:
        if not seg:
            continue
        if seg.startswith("## ") or seg.startswith("### "):
            if cur_title or cur_body:
                chunks.append({
                    "title": cur_title,
                    "content": (cur_title + "\n" + "".join(cur_body)).strip(),
                })
            cur_title = seg.strip()
            cur_body = []
        else:
            cur_body.append(seg)
    if cur_title or cur_body:
        chunks.append({
            "title": cur_title,
            "content": (cur_title + "\n" + "".join(cur_body)).strip(),
        })

    chunks = [c for c in chunks if len(c["content"]) >= 50]
    _CHUNKS_CACHE = chunks
    return chunks


def _tokenize(s):
    s = (s or "").lower()
    # Treat both ASCII words and CJK chars as tokens.
    tokens = re.findall(r"[a-z0-9_]+", s)
    cjk = re.findall(r"[\u4e00-\u9fa5]", s)
    return set(tokens) | set(cjk)


def retrieve(query: str, top_k: int = 6):
    chunks = _load_chunks()
    if not chunks or not query:
        return []
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []

    scored = []
    for ch in chunks:
        c_tokens = _tokenize(ch["content"])
        if not c_tokens:
            continue
        overlap = len(q_tokens & c_tokens)
        if overlap == 0:
            continue
        # Simple Jaccard-like score, plus bonus for title overlap.
        title_bonus = len(q_tokens & _tokenize(ch["title"])) * 2
        score = overlap + title_bonus
        scored.append((score, ch))

    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:top_k]]


def format_chunks(chunks):
    if not chunks:
        return "(no relevant knowledge retrieved)"
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"[KB-{i}] {c['title']}\n{c['content'][:600]}")
    return "\n\n".join(parts)
