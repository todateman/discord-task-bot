FROM python:3.11-slim

WORKDIR /app

# 依存インストール（キャッシュ効率化のため先にコピー）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ソースコピー
COPY src/ ./src/
COPY credentials.json .

CMD ["python", "-m", "src.bot"]
