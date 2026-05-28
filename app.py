import json
import uuid
import zlib
import base64
import sys
import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, abort
from database import get_db, init_db

app = Flask(__name__)
app.secret_key = "mini-sentry-secret"

# ──────────────────────────────────────────────
# 只读模式：READ_ONLY=true 时禁止一切写操作
# ──────────────────────────────────────────────
READ_ONLY = os.environ.get("READ_ONLY", "false").strip().lower() == "true"

def _get_dsn_for_project(project, host: str) -> str:
    """根据 project row 和当前 host 拼出 DSN 字符串"""
    return f"http://{project['dsn_key']}@{host}/api/{project['id']}"

def _startup_tasks():
    """
    应用启动时执行：
    1. 打印所有项目的 DSN
    2. 若 READ_ONLY=true，则清空所有项目的事件
    """
    print("\n" + "=" * 60)
    print("[STARTUP] Mini Sentry 启动")
    print(f"[STARTUP] READ_ONLY 模式: {READ_ONLY}")

    db = get_db()
    projects = db.execute("SELECT * FROM projects ORDER BY id ASC").fetchall()

    if not projects:
        print("[STARTUP] 当前没有任何项目")
    else:
        print(f"[STARTUP] 共 {len(projects)} 个项目，DSN 列表：")
        # 尝试从环境变量读取 HOST，方便容器场景下输出正确地址
        host_hint = os.environ.get("SENTRY_HOST", "localhost:5000")
        for p in projects:
            dsn = f"http://{p['dsn_key']}@{host_hint}/api/{p['id']}"
            print(f"[STARTUP]   [{p['id']}] {p['name']:<20}  DSN: {dsn}")

    if READ_ONLY:
        print("[STARTUP] READ_ONLY=true，正在清空所有项目的事件...")
        deleted_total = 0
        for p in projects:
            result = db.execute("DELETE FROM events WHERE project_id = ?", (p['id'],))
            deleted_total += result.rowcount
            print(f"[STARTUP]   清空项目 [{p['id']}] {p['name']}，删除 {result.rowcount} 条事件")
        db.commit()
        print(f"[STARTUP] 清空完成，共删除 {deleted_total} 条事件")

    db.close()
    print("=" * 60 + "\n")


# ──────────────────────────────────────────────
# 工具函数（不变）
# ──────────────────────────────────────────────

def _parse_sentry_auth(auth_header: str) -> dict:
    """解析 X-Sentry-Auth 头部"""
    parts = {}
    if auth_header:
        for part in auth_header.split(","):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                parts[k.strip().replace("Sentry ", "")] = v.strip()
    return parts

def _extract_dsn_key(request) -> str | None:
    """从请求中提取 sentry_key"""
    auth = request.headers.get("X-Sentry-Auth", "")
    parts = _parse_sentry_auth(auth)
    key = parts.get("sentry_key")
    if not key:
        key = request.args.get("sentry_key")
    return key

def _decompress_body(request) -> dict | None:
    """解压并解析请求体（支持 gzip/deflate/raw JSON）"""
    data = request.get_data()
    content_encoding = request.headers.get("Content-Encoding", "")
    try:
        if "gzip" in content_encoding or "deflate" in content_encoding:
            data = zlib.decompress(data)
        return json.loads(data.decode("utf-8", errors="replace"))
    except Exception:
        try:
            return json.loads(data)
        except Exception:
            return None

def _build_title(payload: dict) -> str:
    """从 payload 提取可读的错误标题"""
    exc = payload.get("exception", {})
    values = exc.get("values", [])
    if values:
        last = values[-1]
        etype = last.get("type", "")
        evalue = last.get("value", "")
        return f"{etype}: {evalue}" if etype else evalue
    if payload.get("message"):
        msg = payload["message"]
        if isinstance(msg, dict):
            return msg.get("formatted", str(msg))
        return str(msg)
    return payload.get("culprit", "Unknown Error")

def _extract_stacktrace(payload: dict) -> str | None:
    """提取 stacktrace 为可读字符串"""
    exc = payload.get("exception", {})
    values = exc.get("values", [])
    lines = []
    for exc_val in values:
        etype = exc_val.get("type", "")
        evalue = exc_val.get("value", "")
        lines.append(f"{etype}: {evalue}")
        st = exc_val.get("stacktrace", {})
        frames = st.get("frames", [])
        for frame in frames:
            fn = frame.get("filename", "?")
            lineno = frame.get("lineno", "?")
            func = frame.get("function", "?")
            lines.append(f"  File \"{fn}\", line {lineno}, in {func}")
            ctx = frame.get("context_line", "").strip()
            if ctx:
                lines.append(f"    {ctx}")
    return "\n".join(lines) if lines else None


# ──────────────────────────────────────────────
# Sentry SDK 兼容接收端点（只读模式下仍然允许接收，因为 ingest 是写事件，不是 clear）
# ──────────────────────────────────────────────

@app.route("/api/<int:project_id>/store/", methods=["POST"])
@app.route("/api/<int:project_id>/envelope/", methods=["POST"])
def sentry_ingest(project_id):
    import traceback

    print(f"\n{'='*60}")
    print(f"[INGEST] {request.method} {request.path}")
    print(f"[INGEST] Content-Type     : {request.headers.get('Content-Type', '-')}")
    print(f"[INGEST] Content-Encoding : {request.headers.get('Content-Encoding', '-')}")
    print(f"[INGEST] X-Sentry-Auth    : {request.headers.get('X-Sentry-Auth', '-')}")
    print(f"[INGEST] READ_ONLY        : {READ_ONLY}")

    # READ_ONLY 模式下不接受新事件写入
    if READ_ONLY:
        print(f"[INGEST] ⛔ READ_ONLY=true，拒绝写入事件")
        return jsonify({"id": str(uuid.uuid4())}), 200

    dsn_key = _extract_dsn_key(request)
    print(f"[INGEST] Extracted DSN key: {dsn_key}")

    db = get_db()
    project = db.execute(
        "SELECT * FROM projects WHERE id = ? AND dsn_key = ?",
        (project_id, dsn_key)
    ).fetchone()

    if not project:
        all_projects = db.execute("SELECT id, name, dsn_key FROM projects").fetchall()
        print(f"[INGEST] ❌ 鉴权失败！数据库中的项目：")
        for p in all_projects:
            print(f"         id={p['id']}  key={p['dsn_key']}  name={p['name']}")
        db.close()
        return jsonify({"error": "Invalid DSN or project"}), 403

    print(f"[INGEST] ✅ 项目匹配：id={project['id']} name={project['name']}")

    raw_bytes = request.get_data()
    content_encoding = request.headers.get("Content-Encoding", "")

    try:
        if "gzip" in content_encoding:
            import gzip
            raw_bytes = gzip.decompress(raw_bytes)
            print(f"[INGEST] gzip 解压后长度: {len(raw_bytes)}")
        elif "deflate" in content_encoding:
            raw_bytes = zlib.decompress(raw_bytes)
            print(f"[INGEST] deflate 解压后长度: {len(raw_bytes)}")
    except Exception as e:
        print(f"[INGEST] ⚠️  解压失败: {e}")

    raw_text = raw_bytes.decode("utf-8", errors="replace")
    print(f"[INGEST] Body 长度: {len(raw_text)} chars")
    print(f"[INGEST] Body 前 500 chars:\n{raw_text[:500]}")

    payload = None

    if "envelope" in request.path:
        lines = raw_text.splitlines()
        print(f"[INGEST] Envelope 共 {len(lines)} 行")
        for i, line in enumerate(lines):
            print(f"[INGEST]   line[{i}]: {line[:120]}")

        i = 1
        while i < len(lines):
            header_line = lines[i].strip()
            payload_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
            i += 2

            if not header_line:
                continue

            try:
                item_header = json.loads(header_line)
            except Exception:
                print(f"[INGEST]   ⚠️  item header 解析失败: {header_line[:80]}")
                continue

            item_type = item_header.get("type", "")
            print(f"[INGEST]   item type: {item_type}")

            if item_type == "event" and payload_line:
                try:
                    payload = json.loads(payload_line)
                    print(f"[INGEST]   ✅ event payload 解析成功，keys: {list(payload.keys())}")
                    break
                except Exception as e:
                    print(f"[INGEST]   ❌ event payload 解析失败: {e}")
                    print(f"[INGEST]      payload_line: {payload_line[:200]}")
    else:
        try:
            payload = json.loads(raw_text)
            print(f"[INGEST] store payload 解析成功，keys: {list(payload.keys())}")
        except Exception as e:
            print(f"[INGEST] ❌ store payload 解析失败: {e}")

    if not payload:
        print(f"[INGEST] ⚠️  payload 为空，跳过存储（非 event 类型 item 属正常，如 session/transaction）")
        db.close()
        return jsonify({"id": str(uuid.uuid4())}), 200

    try:
        title = _build_title(payload)
        stacktrace = _extract_stacktrace(payload)
        req_data = json.dumps(payload.get("request", {})) if payload.get("request") else None
        tags = json.dumps(payload.get("tags", {}))
        extra = json.dumps(payload.get("extra", {}))

        print(f"[INGEST] 准备写入: level={payload.get('level')} title={title[:80]}")

        db.execute("""
            INSERT INTO events
                (project_id, event_id, level, title, message, culprit, platform,
                 environment, release, stacktrace, request_data, extra, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id,
            payload.get("event_id", str(uuid.uuid4())),
            payload.get("level", "error"),
            title,
            json.dumps(payload.get("message", "")),
            payload.get("culprit", ""),
            payload.get("platform", "python"),
            payload.get("environment", "production"),
            payload.get("release", ""),
            stacktrace,
            req_data,
            extra,
            tags,
        ))
        db.commit()
        print(f"[INGEST] ✅ 事件写入成功！")
    except Exception as e:
        print(f"[INGEST] ❌ 写入数据库失败: {e}")
        traceback.print_exc()
    finally:
        db.close()

    return jsonify({"id": payload.get("event_id", str(uuid.uuid4()))}), 200


# ──────────────────────────────────────────────
# 管理界面路由
# ──────────────────────────────────────────────

@app.route("/")
def index():
    db = get_db()
    projects = db.execute("""
        SELECT p.*, COUNT(e.id) as event_count
        FROM projects p
        LEFT JOIN events e ON e.project_id = p.id
        GROUP BY p.id
        ORDER BY p.created_at DESC
    """).fetchall()
    db.close()
    return render_template("index.html", projects=projects, read_only=READ_ONLY)

@app.route("/projects/create", methods=["POST"])
def create_project():
    if READ_ONLY:
        print(f"[CREATE_PROJECT] ⛔ READ_ONLY=true，拒绝创建项目")
        return jsonify({"error": "Read-only mode"}), 403
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("index"))
    dsn_key = uuid.uuid4().hex
    db = get_db()
    try:
        db.execute("INSERT INTO projects (name, dsn_key) VALUES (?, ?)", (name, dsn_key))
        db.commit()
        print(f"[CREATE_PROJECT] 创建项目: name={name} dsn_key={dsn_key}")
    except Exception as e:
        print(f"[CREATE_PROJECT] 失败: {e}")
    db.close()
    return redirect(url_for("index"))

@app.route("/projects/<int:project_id>")
def project_detail(project_id):
    db = get_db()
    project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        abort(404)
    level_filter = request.args.get("level", "")
    if level_filter:
        events = db.execute(
            "SELECT * FROM events WHERE project_id = ? AND level = ? ORDER BY created_at DESC LIMIT 200",
            (project_id, level_filter)
        ).fetchall()
    else:
        events = db.execute(
            "SELECT * FROM events WHERE project_id = ? ORDER BY created_at DESC LIMIT 200",
            (project_id,)
        ).fetchall()
    db.close()

    host = request.host
    dsn = f"http://{project['dsn_key']}@{host}/api/{project_id}"
    print(f"[PROJECT_DETAIL] project_id={project_id} read_only={READ_ONLY} events={len(events)}")
    return render_template(
        "project_detail.html",
        project=project,
        events=events,
        dsn=dsn,
        level_filter=level_filter,
        read_only=READ_ONLY,
    )

@app.route("/projects/<int:project_id>/events/<int:event_db_id>")
def event_detail(project_id, event_db_id):
    db = get_db()
    event = db.execute(
        "SELECT * FROM events WHERE id = ? AND project_id = ?",
        (event_db_id, project_id)
    ).fetchone()
    project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    db.close()
    if not event:
        abort(404)
    print(f"[EVENT_DETAIL] event_id={event_db_id} read_only={READ_ONLY}")
    return render_template("event_detail.html", event=event, project=project, read_only=READ_ONLY)

@app.route("/projects/<int:project_id>/events/<int:event_db_id>/delete", methods=["POST"])
def delete_event(project_id, event_db_id):
    if READ_ONLY:
        print(f"[DELETE_EVENT] ⛔ READ_ONLY=true，拒绝删除 event_id={event_db_id}")
        return jsonify({"error": "Read-only mode"}), 403
    db = get_db()
    db.execute("DELETE FROM events WHERE id = ? AND project_id = ?", (event_db_id, project_id))
    db.commit()
    db.close()
    print(f"[DELETE_EVENT] 删除事件 event_id={event_db_id} project_id={project_id}")
    return redirect(url_for("project_detail", project_id=project_id))

@app.route("/projects/<int:project_id>/clear", methods=["POST"])
def clear_events(project_id):
    if READ_ONLY:
        print(f"[CLEAR_EVENTS] ⛔ READ_ONLY=true，拒绝清空 project_id={project_id}")
        return jsonify({"error": "Read-only mode"}), 403
    db = get_db()
    result = db.execute("DELETE FROM events WHERE project_id = ?", (project_id,))
    db.commit()
    db.close()
    print(f"[CLEAR_EVENTS] 清空 project_id={project_id}，删除 {result.rowcount} 条事件")
    return redirect(url_for("project_detail", project_id=project_id))


# ──────────────────────────────────────────────
# 启动
# ──────────────────────────────────────────────

init_db()
_startup_tasks()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
