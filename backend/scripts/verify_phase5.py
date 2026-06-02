"""阶段 5 端到端验证：建项目→角色→大纲→生成第1章（含审改闭环 + AI味分数）
→断言 reviewed/可能 revised→手动 revise(fix) 与 revise(anti-detect) 端点。

依赖本地后端 http://localhost:8000。
运行：backend/.venv/Scripts/python.exe scripts/verify_phase5.py
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8000"


def _req(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _sse(method: str, path: str, body: dict) -> list[tuple[str, dict]]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    events: list[tuple[str, dict]] = []
    with urllib.request.urlopen(req, timeout=900) as resp:
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
        "title": "验证·审改闭环",
        "genre": "悬疑奇幻",
        "premise": "守夜人林骁在边境古城追查与亡魂有关的连环失踪案，同伴有医师苏挽。",
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
                    {"volume_count": 1, "chapters_per_volume": 2})
    print(st, f"{len(vols)} 卷" if isinstance(vols, list) else vols)
    ok = ok and st < 300
    ch1 = vols[0]["chapters"][0]["id"]

    print("== 4. 生成第 1 章（写作→记忆→审校→自动修订闭环） ==")
    ev = _sse("POST", f"/api/chapters/{ch1}/generate", {"word_count": 600})
    seq = [e for e, _ in ev if e != "token"]
    print("   事件序列:", seq)
    reviewed = next((d for e, d in ev if e == "reviewed"), None)
    revised = [d for e, d in ev if e == "revised"]
    ok = ok and "done" in seq and reviewed is not None
    if reviewed is not None:
        print(f"   reviewed: 问题数={len(reviewed.get('issues', []))} "
              f"AI味={reviewed.get('ai_flavor_score')} hits={reviewed.get('ai_flavor_hits')}")
        ok = ok and "ai_flavor_score" in reviewed
        needs_fix = any(i.get("severity") in ("high", "medium")
                        for i in reviewed.get("issues", []))
        if needs_fix:
            print("   存在 high/medium 问题 → 期望触发 revised")
            ok = ok and len(revised) >= 1
        else:
            print("   无 high/medium 问题 → 不强制 revised")
    for r in revised:
        print(f"   revised: round={r.get('round')} "
              f"{r.get('before_issues')}→{r.get('after_issues')} 问题 "
              f"AI味={r.get('ai_flavor_score')}")

    print("== 5. 手动 revise(fix) 端点 ==")
    st, res = _req("POST", f"/api/chapters/{ch1}/revise", {"mode": "fix"})
    if st < 300 and isinstance(res, dict):
        rv = res.get("review") or {}
        print("   OK | 新正文字数:", len(res.get("content", "")),
              "| 问题数:", len(rv.get("issues", [])),
              "| AI味:", rv.get("ai_flavor_score"))
        ok = ok and len(res.get("content", "")) > 0 and "ai_flavor_score" in rv
    else:
        print("   fix 失败:", st, res)
        ok = False

    print("== 6. 手动 revise(anti-detect) 端点 ==")
    st, res = _req("POST", f"/api/chapters/{ch1}/revise", {"mode": "anti-detect"})
    if st < 300 and isinstance(res, dict):
        rv = res.get("review") or {}
        print("   OK | 新正文字数:", len(res.get("content", "")),
              "| AI味:", rv.get("ai_flavor_score"), "| hits:", rv.get("ai_flavor_hits"))
        ok = ok and len(res.get("content", "")) > 0
    else:
        print("   anti-detect 失败:", st, res)
        ok = False

    print("== 7. 项目详情应带最新审校（含 AI味分数） ==")
    st, detail = _req("GET", f"/api/projects/{pid}")
    if st < 300 and isinstance(detail, dict):
        all_chaps = [c for v in detail.get("volumes", []) for c in v.get("chapters", [])]
        c1 = next((c for c in all_chaps if c["id"] == ch1), None)
        review = c1.get("review") if c1 else None
        print("   章节带 review:", review is not None,
              "| AI味:", (review or {}).get("ai_flavor_score"))
        ok = ok and review is not None and "ai_flavor_score" in (review or {})
    else:
        print("   (项目详情获取失败)", st)
        ok = False

    print("\n==== 结果:", "PASS ✅" if ok else "FAIL ❌", "====")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
