import logging
import discord
from src.config import DISCORD_TOKEN, TASK_CHANNELS
from src.ai_agent import parse_message
from src.sheets import update_task_status, add_task
from src.scheduler import setup_scheduler
from src.config import STATUS_DONE, STATUS_IN_PROGRESS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Bot設定
# ──────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True  # メッセージ本文を読むために必要
bot = discord.Client(intents=intents)


# ──────────────────────────────────────────────
# イベントハンドラ
# ──────────────────────────────────────────────

@bot.event
async def on_ready():
    logger.info(f"ログイン完了: {bot.user} (ID: {bot.user.id})")
    logger.info(f"監視チャンネル: {TASK_CHANNELS}")
    scheduler = setup_scheduler(bot)
    scheduler.start()


@bot.event
async def on_message(message: discord.Message):
    # Bot自身のメッセージは無視
    if message.author.bot:
        return

    # 監視チャンネル以外は無視（TASK_CHANNELSが空なら全チャンネル対象）
    if TASK_CHANNELS:
        if message.channel.name not in TASK_CHANNELS:
            return

    content = message.content.strip()
    if not content:
        return

    # AIでメッセージを解析
    parsed = parse_message(content)
    action = parsed.get("action", "none")
    task_name = parsed.get("task_name", "")

    logger.info(
        f"[#{message.channel.name}] {message.author.name}: "
        f'"{content[:50]}" → action={action}, task="{task_name}"'
    )

    if action == "complete" and task_name:
        updated = update_task_status(task_name, STATUS_DONE)
        if updated:
            await message.reply(f"✅ **{updated}** を「完了」に更新しました！")
        else:
            await message.reply(
                f"⚠️ タスク「{task_name}」が見つかりませんでした。\n"
                "タスク名を確認するか、スプレッドシートを直接ご確認ください。"
            )

    elif action == "in_progress" and task_name:
        updated = update_task_status(task_name, STATUS_IN_PROGRESS)
        if updated:
            await message.reply(f"🔄 **{updated}** を「進行中」に更新しました！")
        else:
            await message.reply(f"⚠️ タスク「{task_name}」が見つかりませんでした。")

    elif action == "add" and task_name:
        task_info = {
            "task_name": task_name,
            "category":  parsed.get("category", ""),
            "priority":  parsed.get("priority", "中"),
            "due_date":  parsed.get("due_date", ""),
            "assignee":  parsed.get("assignee", ""),
        }
        new_id = add_task(task_info)
        summary = (
            f"📝 **{task_name}** を登録しました！\n"
            f"　ID: `{new_id}` ／ 優先度: {task_info['priority']}"
        )
        if task_info["due_date"]:
            summary += f" ／ 期限: {task_info['due_date']}"
        if task_info["assignee"]:
            summary += f" ／ 担当: {task_info['assignee']}"
        await message.reply(summary)

    # action == "none" は何もしない（雑談等はスルー）


# ──────────────────────────────────────────────
# エントリポイント
# ──────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
