import json
import logging
import anthropic
from src.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)
_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ──────────────────────────────────────────────
# メッセージ解析
# ──────────────────────────────────────────────

PARSE_SYSTEM = """
あなたはDiscordのタスク管理Botです。
ユーザーのメッセージを解析し、タスク操作を判定してください。

以下のJSONのみを返してください（説明文は不要）:

{
  "action": "complete" | "in_progress" | "add" | "list" | "report" | "none",
  "task_name": "タスク名（actionがcomplete/in_progress/addのとき）",
  "category": "分類（addのとき、不明なら空文字）",
  "priority": "高" | "中" | "低"（addのとき、不明なら"中"）,
  "due_date": "YYYY/MM/DD（addのとき、不明なら空文字）",
  "assignee": "担当者名（addのとき、不明なら空文字）",
  "reason": "noneの理由（actionがnoneのとき）"
}

判定ルール:
- 「完了」「終わった」「done」「finished」などが含まれ、タスク名が読み取れる → "complete"
- 「着手」「開始」「進行中」「やってる」「WIP」などが含まれる → "in_progress"
- 「追加」「登録」「新規」「タスク:」「TODO:」で始まる → "add"
- 「タスク一覧」「残っているタスク」「タスクを教えて」「何のタスク」「タスクある」など、タスクの一覧・確認を求めている → "list"
- 「週次レポート」「週次進捗レポート」などを投稿・表示・確認するよう求めている → "report"
- それ以外（雑談・質問・コマンド以外）→ "none"
"""


def parse_message(content: str) -> dict:
    """メッセージを解析してアクション辞書を返す"""
    try:
        resp = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system=PARSE_SYSTEM,
            messages=[{"role": "user", "content": content}],
        )
        text = resp.content[0].text.strip()
        # JSONブロックのみ抽出
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        logger.warning(f"parse_message エラー: {e}")
        return {"action": "none", "reason": str(e)}


# ──────────────────────────────────────────────
# 週次レポート生成
# ──────────────────────────────────────────────

REPORT_SYSTEM = """
あなたはプロジェクト管理アシスタントです。
未完了タスク一覧をもとに、Discordに投稿する週次進捗レポートを生成してください。

フォーマット要件:
- Discordのmarkdownを使用（**太字**、```コードブロック```、> 引用など）
- 全体の状況を2〜3文で簡潔にサマリー
- 優先度「高」のタスクを先頭にリストアップ
- 期限が近いもの（3日以内）は ⚠️ マークを付ける
- 担当者ごとのタスク数も簡単に表示
- 全体を300文字以内に収める
- 最後に「週次リマインド from タスクBot」と付ける

今日の日付: {today}
"""


def generate_weekly_report(tasks: list[dict], today: str, sheets_url: str = "") -> str:
    """未完了タスクリストから週次レポートを生成"""
    sheets_line = f"\n📋 [タスク一覧スプレッドシート]({sheets_url})" if sheets_url else ""

    if not tasks:
        return f"現在、未完了タスクはありません。お疲れ様でした！{sheets_line}\n\n_週次リマインド from タスクBot_"

    task_text = "\n".join(
        f"- [{t['priority']}] {t['task_name']} / 担当:{t['assignee'] or '未定'}"
        f" / 期限:{t['due_date'] or '未設定'} / 状態:{t['status']}"
        for t in tasks
    )

    try:
        resp = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=600,
            system=REPORT_SYSTEM.format(today=today),
            messages=[{"role": "user", "content": f"未完了タスク一覧:\n{task_text}"}],
        )
        report = resp.content[0].text.strip()
        return f"{report}{sheets_line}"
    except Exception as e:
        logger.error(f"generate_weekly_report エラー: {e}")
        # フォールバック: シンプルなリスト
        lines = ["**【週次タスクリマインド】**\n"]
        for t in tasks:
            lines.append(
                f"・[{t['priority']}] {t['task_name']} "
                f"({t['assignee'] or '未定'} / {t['due_date'] or '期限未設定'})"
            )
        lines.append(f"\n_週次リマインド from タスクBot_{sheets_line}")
        return "\n".join(lines)
