import json
import logging
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from rapidfuzz import fuzz
from src.config import (
    SPREADSHEET_ID, SHEET_NAME, CREDENTIALS_FILE, GOOGLE_CREDENTIALS,
    COL_ID, COL_TASK_NAME, COL_CATEGORY, COL_PRIORITY,
    COL_DUE_DATE, COL_ASSIGNEE, COL_STATUS, COL_PROGRESS,
    STATUS_TODO, STATUS_DONE, STATUS_CANCELED,
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_service_cache = None


def _get_service():
    global _service_cache
    if _service_cache is None:
        if GOOGLE_CREDENTIALS:
            creds_dict = json.loads(GOOGLE_CREDENTIALS)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        _service_cache = build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets()
    return _service_cache


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


FUZZY_THRESHOLD = 70  # 類似度スコアの閾値（0〜100）


def find_task_row_in_rows(task_name_hint: str, rows: list[list]) -> tuple[int, list] | tuple[None, None]:
    """
    渡された行データ（キャッシュ）からタスクを検索する。
    sync_history など繰り返し検索する場面で _get_all_rows() の重複呼び出しを避けるために使う。
    """
    hint = task_name_hint.strip().lower()

    for i, row in enumerate(rows):
        if len(row) > COL_TASK_NAME and hint in row[COL_TASK_NAME].lower():
            return i + 2, row

    best_score = 0
    best_index = None
    for i, row in enumerate(rows):
        if len(row) <= COL_TASK_NAME:
            continue
        score = fuzz.token_set_ratio(hint, row[COL_TASK_NAME].lower())
        if score > best_score:
            best_score = score
            best_index = i

    if best_score >= FUZZY_THRESHOLD and best_index is not None:
        row = rows[best_index]
        logger.info(f"あいまい検索でマッチ: '{task_name_hint}' → '{row[COL_TASK_NAME]}' (スコア: {best_score})")
        return best_index + 2, row

    return None, None


def find_task_row(task_name_hint: str) -> tuple[int, list] | tuple[None, None]:
    """
    タスク名でシート行番号を探す。
    1. 部分一致（完全に含む）
    2. あいまい検索（rapidfuzz による類似度スコア）
    返り値: (1始まりのシート行番号, 行データ) または (None, None)
    """
    rows = _get_all_rows()
    hint = task_name_hint.strip().lower()

    # 1. 部分一致
    for i, row in enumerate(rows):
        if len(row) > COL_TASK_NAME and hint in row[COL_TASK_NAME].lower():
            return i + 2, row  # ヘッダー行(1) + 0始まりインデックス → +2

    # 2. あいまい検索
    best_score = 0
    best_index = None
    for i, row in enumerate(rows):
        if len(row) <= COL_TASK_NAME:
            continue
        score = fuzz.token_set_ratio(hint, row[COL_TASK_NAME].lower())
        if score > best_score:
            best_score = score
            best_index = i

    if best_score >= FUZZY_THRESHOLD and best_index is not None:
        row = rows[best_index]
        logger.info(f"あいまい検索でマッチ: '{task_name_hint}' → '{row[COL_TASK_NAME]}' (スコア: {best_score})")
        return best_index + 2, row

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
    now = (datetime.now() + timedelta(hours=9)).strftime("%Y/%m/%d %H:%M")  # JSTで記録する
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
