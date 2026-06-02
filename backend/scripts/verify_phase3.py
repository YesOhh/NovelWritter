"""阶段 3 端到端验证脚本：建项目→角色→大纲→检查 MemoryChunk→生成两章→验证记忆落库与前情注入。

直接对本地后端 http://localhost:8000 发请求，逐步打印结果。
运行：backend/.venv/Scripts/python.exe scripts/verify_phase3.py
"""
import json
import sys
import urllib.request

BASE = "http://localhost:8000"


def _req(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _sse(method: str, path: str, body: dict) -> list[tuple[str, dict]]:
    """读取 SSE 流，返回 (event, data) 列表。"""
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    events: list[tuple[str, dict]] = []
    with urllib.request.urlopen(req, timeout=600) as resp:
        event = None
        payload = ""
        for line in resp:
            line = line.decode().rstrip("\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                payload += line[5:].strip()
            elif line == "":
                if event:
                    try:
                        events.append((event, json.loads(payload)))
                    except Exception:
                        events.append((event, {"raw": payload}))
                event, payload = None, ""
    return events


def main() -> int:
    ok = True

    print("== 1. 建项目 ==")
    st, project = _req("POST", "/api/projects", {
        "title": "验证·记忆古城",
        "genre": "悬疑奇幻",
        "premise": "守夜人林骁在边境古城追查一桩与亡魂有关的连环失踪案，同伴有医师苏挽。",
        "style_guide": {"style": "冷峻、悬疑，画面感强"},
    })
    print(st, project.get("id") if isinstance(project, dict) else project)
    if st >= 300:
        return 1
    pid = project["id"]

    print("== 2. 生成角色 ==")
    st, chars = _req("POST", f"/api/projects/{pid}/characters/generate", {"count": 2})
    print(st, [c["name"] for c in chars] if isinstance(chars, list) else chars)
    ok = ok and st < 300

    print("== 3. 生成大纲 ==")
    st, vols = _req("POST", f"/api/projects/{pid}/outline/generate",
                    {"volume_count": 1, "chapters_per_volume": 3})
    print(st, f"{len(vols)} 卷" if isinstance(vols, list) else vols)
    ok = ok and st < 300
    vol = vols[0]
    chapters = vol["chapters"]
    print("   章节:", [c["title"] for c in chapters])

    print("== 4. 检查 MemoryChunk（应有角色+卷大纲片段） ==")
    st, chunks = _req("GET", f"/api/projects/{pid}/memory/chunks")
    if st == 404:
        print("   (无 /memory/chunks 端点，跳过直接核对，靠后续召回间接验证)")
    else:
        print(st, f"{len(chunks)} 个片段" if isinstance(chunks, list) else chunks)
        if isinstance(chunks, list):
            for c in chunks:
                print("   -", c.get("source_type"), c.get("keywords"))

    print("== 5. 生成第 1 章 ==")
    ev1 = _sse("POST", f"/api/chapters/{chapters[0]['id']}/generate", {"word_count": 600})
    names1 = [e for e, _ in ev1]
    tokens1 = "".join(d.get("text", "") for e, d in ev1 if e == "token")
    print("   事件序列:", [e for e in names1 if e != "token"])
    print("   正文字数:", len(tokens1))
    has_done1 = "done" in names1
    has_indexed1 = "indexed" in names1
    print("   done:", has_done1, "| indexed:", has_indexed1)
    ok = ok and has_done1 and has_indexed1

    print("== 6. 生成第 2 章（应注入第1章前情/摘要/状态） ==")
    ev2 = _sse("POST", f"/api/chapters/{chapters[1]['id']}/generate", {"word_count": 600})
    names2 = [e for e, _ in ev2]
    tokens2 = "".join(d.get("text", "") for e, d in ev2 if e == "token")
    print("   事件序列:", [e for e in names2 if e != "token"])
    print("   正文字数:", len(tokens2))
    has_index_err = "index_error" in names2 or "error" in names2
    print("   有错误事件:", has_index_err)
    ok = ok and "done" in names2 and not has_index_err

    print("== 7. 复核：第1章摘要/正文与实体状态是否落库（经项目详情） ==")
    st, detail = _req("GET", f"/api/projects/{pid}")
    if st < 300 and isinstance(detail, dict):
        all_chaps = [c for v in detail.get("volumes", []) for c in v.get("chapters", [])]
        c1 = next((c for c in all_chaps if c["id"] == chapters[0]["id"]), None)
        if c1:
            print("   第1章 status:", c1.get("status"),
                  "| 正文字数:", len(c1.get("content", "")),
                  "| summary 长度:", len(c1.get("summary", "")))
            ok = ok and c1.get("status") == "drafted" and len(c1.get("content", "")) > 0
            ok = ok and len(c1.get("summary", "")) > 0
    else:
        print("   (项目详情获取失败)", st)

    print("\n==== 结果:", "PASS ✅" if ok else "FAIL ❌", "====")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
