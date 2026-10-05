# ⬡ Next Sentry

A lightweight, self-hosted error tracking server compatible with the Sentry SDK — built with Flask and SQLite, zero external dependencies.

[![CI](https://github.com/evlos/next_sentry/actions/workflows/docker.yml/badge.svg)](https://github.com/evlos/next_sentry/actions)
[![License: GPL](https://img.shields.io/badge/License-GPL-yellow.svg)](LICENSE)

---

## Preview

![Preview](https://github.com/Evlos/uploads/blob/main/Next%20Sentry%20%E2%80%94%20test%20-%20Google%20Chrome_2026-05-27_22-50-25.jpg?raw=true)

---

## ✨ Features

- 📦 **Drop-in Sentry SDK compatible** — works with any language/framework that supports the Sentry protocol
- 🗄️ **SQLite-backed** — no Postgres, no Redis, no external services required
- 📶 **Severity ribbon** — a live raster of recent events in the rail, so you can see the shape of a failure without reading a single number
- 🔍 **Event detail view** — stacktrace with the raising frame marked, tags, extra context, request data
- 🎛️ **Level filtering** — filter events by `error`, `warning`, `info`, `debug`
- 🌓 **Dark / Light theme** — follows the OS preference, persisted via `localStorage`
- 📋 **One-click DSN copy** — copy the DSN or the ready-to-paste `sentry_sdk.init(...)` snippet
- ✈️ **No CDN at runtime** — Tailwind and the fonts are compiled and vendored into `static/`
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

### Frontend

Tailwind is compiled ahead of time and `static/app.css` is committed, so the
app itself needs neither Node nor a network connection at runtime. Node is only
required when you change the UI:

```bash
npm install
make build      # rebuild static/app.css, then audit contrast
```

| Command | What it does |
| --- | --- |
| `make css` | Compile `src/app.css` → `static/app.css` |
| `make fonts` | Re-download the vendored woff2 subsets into `static/fonts/` |
| `make contrast` | WCAG AA audit of every token pair the UI renders |
| `make assets` | All of the above |

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
├── src/app.css         # Tailwind entry: tokens + component layer
├── src/fonts.css       # generated @font-face rules
├── static/app.css      # built stylesheet (committed)
├── static/fonts/       # vendored woff2 subsets (committed)
├── scripts/
│   ├── fetch-fonts.mjs # downloads the latin subsets
│   └── check-contrast.mjs
├── templates/
│   ├── base.html       # shell: rail, ribbon slot, theme switcher
│   ├── _ribbon.html    # the severity ribbon macro
│   ├── index.html      # Instance readout + project list
│   ├── project_detail.html
│   ├── event_detail.html
│   └── 404.html
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
