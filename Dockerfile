FROM python:3.12-alpine

LABEL org.opencontainers.image.source="https://github.com/evlos/mini-sentry"
LABEL org.opencontainers.image.description="Lightweight self-hosted Sentry-compatible error tracker"
LABEL org.opencontainers.image.licenses="MIT"

# 安装编译依赖（Alpine 下 gevent/greenlet 等可能需要，此处仅 flask+gunicorn 则无需）
RUN apk add --no-cache gcc musl-dev libffi-dev

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 数据目录（SQLite 文件挂载点）
RUN mkdir -p /app/data

ENV DB_PATH=/app/data/next_sentry.db
ENV FLASK_ENV=production
ENV PORT=5000

EXPOSE 5000

# 使用 gunicorn 生产启动，2 worker 适配低资源环境
CMD ["gunicorn", "app:app", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
