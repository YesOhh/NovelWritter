"""阶段 4 端到端验证：建项目→角色→大纲→生成第1章（含审校闭环）→断言 reviewed 报告→单独重审。

依赖本地后端 http://localhost:8000。
运行：backend/.venv/Scripts/python.exe scripts/verify_phase4.py
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
        with urllib.request.urlopen(req, timeout=300) as resp:
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
        "title": "验证·审校闭环",
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
    chapters = vols[0]["chapters"]
    ch1 = chapters[0]["id"]

    print("== 4. 生成第 1 章（写作→记忆→审校闭环） ==")
    ev = _sse("POST", f"/api/chapters/{ch1}/generate", {"word_count": 600})
    names = [e for e, _ in ev]
    seq = [e for e in names if e != "token"]
    print("   事件序列:", seq)
    reviewed = next((d for e, d in ev if e == "reviewed"), None)
    has_done = "done" in names
    has_reviewed = reviewed is not None
    print("   done:", has_done, "| reviewed:", has_reviewed)
    ok = ok and has_done and has_reviewed
    if reviewed is not None:
        issues = reviewed.get("issues", [])
        print(f"   审校问题数: {len(issues)} | 总评长度: {len(reviewed.get('summary', ''))}")
        # 结构断言：summary 非空；若有问题，字段齐全。
        ok = ok and isinstance(issues, list)
        ok = ok and len(reviewed.get("summary", "")) > 0
        for it in issues:
            ok = ok and "type" in it and "severity" in it and "description" in it
            print(f"     - [{it.get('type')}/{it.get('severity')}] {it.get('description', '')[:40]}")

    print("== 5. 项目详情应带最近审校报告 ==")
    st, detail = _req("GET", f"/api/projects/{pid}")
    if st < 300 and isinstance(detail, dict):
        all_chaps = [c for v in detail.get("volumes", []) for c in v.get("chapters", [])]
        c1 = next((c for c in all_chaps if c["id"] == ch1), None)
        review = c1.get("review") if c1 else None
        print("   章节带 review:", review is not None)
        ok = ok and review is not None and "summary" in (review or {})
    else:
        print("   (项目详情获取失败)", st)
        ok = False

    print("== 6. 单独重审端点 ==")
    st, report = _req("POST", f"/api/chapters/{ch1}/review", {})
    if st < 300 and isinstance(report, dict):
        print("   重审 OK | 问题数:", len(report.get("issues", [])),
              "| 总评长度:", len(report.get("summary", "")))
        ok = ok and "summary" in report and "issues" in report
    else:
        print("   重审失败:", st, report)
        ok = False

    print("\n==== 结果:", "PASS ✅" if ok else "FAIL ❌", "====")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
