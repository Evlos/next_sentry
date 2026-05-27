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
    """接收 Sentry SDK 发来的事件（兼容 store 和 envelope 格式）"""
    dsn_key = _extract_dsn_key(request)

    db = get_db()
    project = db.execute(
        "SELECT * FROM projects WHERE id = ? AND dsn_key = ?",
        (project_id, dsn_key)
    ).fetchone()

    if not project:
        db.close()
        return jsonify({"error": "Invalid DSN or project"}), 403

    # envelope 格式：多行 JSON（header\n{}\npayload）
    content_type = request.headers.get("Content-Type", "")
    if "envelope" in request.path or "x-sentry-envelope" in content_type:
        raw = request.get_data().decode("utf-8", errors="replace")
        lines = [l for l in raw.strip().splitlines() if l.strip()]
        payload = None
        for line in lines[2:]:  # 跳过 envelope header 和 item header
            try:
                payload = json.loads(line)
                break
            except Exception:
                continue
        if not payload:
            db.close()
            return jsonify({"id": str(uuid.uuid4())}), 200
    else:
        payload = _decompress_body(request)
        if not payload:
            db.close()
            return jsonify({"error": "Could not parse body"}), 400

    title = _build_title(payload)
    stacktrace = _extract_stacktrace(payload)
    req_data = json.dumps(payload.get("request", {})) if payload.get("request") else None
    tags = json.dumps(payload.get("tags", {}))
    extra = json.dumps(payload.get("extra", {}))

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


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
