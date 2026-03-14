import os
from dotenv import load_dotenv

load_dotenv()

# Discord
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
# 監視するチャンネル名のリスト（空文字は除外）
_task_channels_raw = os.getenv("TASK_CHANNELS") or os.getenv("ASK_CHANNELS", "")
TASK_CHANNELS = [c.strip() for c in _task_channels_raw.split(",") if c.strip()]
REPORT_CHANNEL = os.getenv("REPORT_CHANNEL", "general")   # 週次レポート投稿先チャンネル名

# Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = "claude-haiku-4-5-20251001"  # コスト最小化

# Google Sheets
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "タスク一覧")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.json")
# Fly.io では JSON 全文をシークレットとして渡せる
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS", "").strip()

# スケジューラ設定（JST = UTC+9）
_weekday_raw = os.getenv("WEEKLY_REPORT_DAY", "mon").strip().lower()
_weekday_alias = {
	"monday": "mon",
	"tuesday": "tue",
	"wednesday": "wed",
	"thursday": "thu",
	"friday": "fri",
	"saturday": "sat",
	"sunday": "sun",
}
WEEKLY_REPORT_DAY = _weekday_alias.get(_weekday_raw, _weekday_raw)   # 毎週月曜など
try:
	WEEKLY_REPORT_HOUR = int(os.getenv("WEEKLY_REPORT_HOUR", "9"))  # 09:00 JST
except ValueError:
	WEEKLY_REPORT_HOUR = 9
WEEKLY_REPORT_TIMEZONE = "Asia/Tokyo"

# Sheets列定義
COL_ID         = 0
COL_TASK_NAME  = 1
COL_CATEGORY   = 2
COL_PRIORITY   = 3
COL_DUE_DATE   = 4
COL_ASSIGNEE   = 5
COL_STATUS     = 6
COL_PROGRESS   = 7
COL_UPDATED_AT = 8

PRIORITY_LABELS = {"高": 1, "中": 2, "低": 3}
STATUS_TODO       = "未着手"
STATUS_IN_PROGRESS = "進行中"
STATUS_DONE        = "完了"
STATUS_CANCELED    = "中止"
