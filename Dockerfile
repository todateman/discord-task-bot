FROM python:3.11-slim

WORKDIR /app

# uv をインストール
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 依存インストール（キャッシュ効率化のため先にコピー）
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# ソースコピー
COPY src/ ./src/

CMD ["python", "-m", "src.bot"]
