# ⬡ Next Sentry

A lightweight, self-hosted error tracking server compatible with the Sentry SDK — built with Flask and SQLite, zero external dependencies.

[![CI](https://github.com/evlos/next_sentry/actions/workflows/docker.yml/badge.svg)](https://github.com/evlos/next_sentry/actions)
[![License: GPL](https://img.shields.io/badge/License-GPL-yellow.svg)](LICENSE)

---

## ✨ Features

- 📦 **Drop-in Sentry SDK compatible** — works with any language/framework that supports the Sentry protocol
- 🗄️ **SQLite-backed** — no Postgres, no Redis, no external services required
- 🔍 **Event detail view** — stacktrace, tags, extra context, request data
- 🎛️ **Level filtering** — filter events by `error`, `warning`, `info`, `debug`
- 🌓 **Dark / Light theme** — persisted via `localStorage`
- 🐳 **Multi-arch Docker image** — supports `linux/amd64` and `linux/arm64`

---

## 🚀 Quick Start

### Docker (recommended)

```bash
docker run -d \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -e DB_PATH=/app/data/next_sentry.db \
  --name next_sentry \
  ghcr.io/evlos/next_sentry:latest
```

Then open [http://localhost:5000](http://localhost:5000), create a project, and copy the DSN.

### Local development

```bash
git clone https://github.com/evlos/next_sentry.git
cd next_sentry
pip install -r requirements.txt
python app.py
```

---

## 🔌 SDK Integration

```python
import sentry_sdk

sentry_sdk.init(
    dsn="http://<your-dsn-key>@localhost:5000/api/<project-id>",
    traces_sample_rate=1.0,
)
```

Any language with a Sentry SDK works — Python, Node.js, Go, Ruby, etc.

---

## 🧪 Test Report

```bash
DSN=http://<key>@localhost:5000/api/<id> python test_report.py
```

Runs 9 test cases covering `ZeroDivisionError`, `KeyError`, chained exceptions, deep stacktraces, `capture_message`, and more.

---

## 📁 Project Structure

```
next_sentry/
├── app.py              # Flask application & Sentry ingest endpoints
├── database.py         # SQLite initialization & connection helper
├── test_report.py      # SDK compatibility test script
├── templates/
│   ├── base.html       # Base layout with theme switcher
│   ├── index.html      # Project list
│   ├── project_detail.html
│   └── event_detail.html
├── Dockerfile
├── requirements.txt
└── .github/
    └── workflows/
        └── docker.yml
```

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `data/next_sentry.db` | SQLite database file path |
| `FLASK_ENV` | `production` | Flask environment |
| `PORT` | `5000` | Listening port |

---

## 📄 License

This project is open-sourced under the [GNU General Public License v3.0](LICENSE).
