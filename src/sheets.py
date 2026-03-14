import json
import logging
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from src.config import (
    SPREADSHEET_ID, SHEET_NAME, CREDENTIALS_FILE, GOOGLE_CREDENTIALS,
    COL_ID, COL_TASK_NAME, COL_CATEGORY, COL_PRIORITY,
    COL_DUE_DATE, COL_ASSIGNEE, COL_STATUS, COL_PROGRESS,
    STATUS_TODO, STATUS_DONE, STATUS_CANCELED,
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_service():
    if GOOGLE_CREDENTIALS:
        creds_dict = json.loads(GOOGLE_CREDENTIALS)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds).spreadsheets()


def _get_all_rows() -> list[list]:
    """シートの全行を取得（ヘッダー除く）"""
    svc = _get_service()
    result = svc.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A2:I",
    ).execute()
    return result.get("values", [])


def get_pending_tasks() -> list[dict]:
    """未完了タスクをリストで返す"""
    rows = _get_all_rows()
    tasks = []
    for row in rows:
        while len(row) < 9:
            row.append("")
        if row[COL_STATUS] not in (STATUS_DONE, STATUS_CANCELED):
            tasks.append({
                "id":        row[COL_ID],
                "task_name": row[COL_TASK_NAME],
                "category":  row[COL_CATEGORY],
                "priority":  row[COL_PRIORITY],
                "due_date":  row[COL_DUE_DATE],
                "assignee":  row[COL_ASSIGNEE],
                "status":    row[COL_STATUS],
                "progress":  row[COL_PROGRESS],
            })
    return tasks


def find_task_row(task_name_hint: str) -> tuple[int, list] | tuple[None, None]:
    """
    タスク名（部分一致・大文字小文字無視）でシート行番号を探す。
    返り値: (1始まりのシート行番号, 行データ) または (None, None)
    """
    rows = _get_all_rows()
    hint = task_name_hint.strip().lower()
    for i, row in enumerate(rows):
        if len(row) > COL_TASK_NAME and hint in row[COL_TASK_NAME].lower():
            return i + 2, row  # ヘッダー行(1) + 0始まりインデックス → +2
    return None, None


def update_task_status(task_name_hint: str, new_status: str) -> str:
    """タスクのステータスを更新。成功時はタスク名を返す"""
    row_num, row = find_task_row(task_name_hint)
    if row_num is None:
        return None
    svc = _get_service()
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    svc.values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!G{row_num}:I{row_num}",
        valueInputOption="USER_ENTERED",
        body={"values": [[new_status, row[COL_PROGRESS] if len(row) > COL_PROGRESS else "", now]]},
    ).execute()
    task_name = row[COL_TASK_NAME] if len(row) > COL_TASK_NAME else task_name_hint
    logger.info(f"ステータス更新: {task_name} → {new_status} (行{row_num})")
    return task_name


def add_task(task_info: dict) -> str:
    """新規タスクを末尾に追記。生成したIDを返す"""
    rows = _get_all_rows()
    new_id = f"T{len(rows) + 1:04d}"
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    new_row = [
        new_id,
        task_info.get("task_name", ""),
        task_info.get("category", ""),
        task_info.get("priority", "中"),
        task_info.get("due_date", ""),
        task_info.get("assignee", ""),
        task_info.get("status", STATUS_TODO),
        task_info.get("progress", ""),
        now,
    ]
    svc = _get_service()
    svc.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A:I",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [new_row]},
    ).execute()
    logger.info(f"タスク追加: {new_id} / {new_row[COL_TASK_NAME]}")
    return new_id
