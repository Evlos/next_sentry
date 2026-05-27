import json
import uuid
import zlib
import base64
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, abort
from database import get_db, init_db

app = Flask(__name__)
app.secret_key = "mini-sentry-secret"

# ──────────────────────────────────────────────
# 工具函数
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
# Sentry SDK 兼容接收端点
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

    dsn_key = _extract_dsn_key(request)
    print(f"[INGEST] Extracted DSN key: {dsn_key}")

    db = get_db()
    project = db.execute(
        "SELECT * FROM projects WHERE id = ? AND dsn_key = ?",
        (project_id, dsn_key)
    ).fetchone()

    if not project:
        # 额外打印数据库里实际存的 key，方便比对
        all_projects = db.execute("SELECT id, name, dsn_key FROM projects").fetchall()
        print(f"[INGEST] ❌ 鉴权失败！数据库中的项目：")
        for p in all_projects:
            print(f"         id={p['id']}  key={p['dsn_key']}  name={p['name']}")
        db.close()
        return jsonify({"error": "Invalid DSN or project"}), 403

    print(f"[INGEST] ✅ 项目匹配：id={project['id']} name={project['name']}")

    # ── 解析 Body ──────────────────────────────────────────
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

    # ── Envelope 格式解析 ──────────────────────────────────
    # envelope 结构：每个 item 由两行组成
    #   行1: item header JSON，如 {"type":"event","length":123}
    #   行2: item payload JSON
    # 整体最前面还有一行 envelope header
    payload = None

    if "envelope" in request.path:
        lines = raw_text.splitlines()
        print(f"[INGEST] Envelope 共 {len(lines)} 行")
        for i, line in enumerate(lines):
            print(f"[INGEST]   line[{i}]: {line[:120]}")

        # 从第 1 行开始（跳过 envelope header），每两行一组
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
        # store 格式：直接是 JSON
        try:
            payload = json.loads(raw_text)
            print(f"[INGEST] store payload 解析成功，keys: {list(payload.keys())}")
        except Exception as e:
            print(f"[INGEST] ❌ store payload 解析失败: {e}")

    if not payload:
        print(f"[INGEST] ⚠️  payload 为空，跳过存储（非 event 类型 item 属正常，如 session/transaction）")
        db.close()
        return jsonify({"id": str(uuid.uuid4())}), 200

    # ── 存储 ───────────────────────────────────────────────
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
    return render_template("index.html", projects=projects)

@app.route("/projects/create", methods=["POST"])
def create_project():
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("index"))
    dsn_key = uuid.uuid4().hex
    db = get_db()
    try:
        db.execute("INSERT INTO projects (name, dsn_key) VALUES (?, ?)", (name, dsn_key))
        db.commit()
    except Exception:
        pass
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
    return render_template("project_detail.html", project=project, events=events, dsn=dsn, level_filter=level_filter)

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
    return render_template("event_detail.html", event=event, project=project)

@app.route("/projects/<int:project_id>/events/<int:event_db_id>/delete", methods=["POST"])
def delete_event(project_id, event_db_id):
    db = get_db()
    db.execute("DELETE FROM events WHERE id = ? AND project_id = ?", (event_db_id, project_id))
    db.commit()
    db.close()
    return redirect(url_for("project_detail", project_id=project_id))

@app.route("/projects/<int:project_id>/clear", methods=["POST"])
def clear_events(project_id):
    db = get_db()
    db.execute("DELETE FROM events WHERE project_id = ?", (project_id,))
    db.commit()
    db.close()
    return redirect(url_for("project_detail", project_id=project_id))


init_db()
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
