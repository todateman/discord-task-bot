import gc
import asyncio
import logging
import discord
from discord import app_commands
from datetime import datetime, timedelta, timezone
from src.config import DISCORD_TOKEN, TASK_CHANNELS
from src.ai_agent import parse_message
from src.sheets import update_task_status, add_task, find_task_row_in_rows, _get_all_rows, get_pending_tasks
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
tree = app_commands.CommandTree(bot)

DEFAULT_HISTORY_DAYS = 30
SYNC_BATCH_SIZE = 20  # この件数ごとに進捗報告 & GC

# Claude API を呼ぶ前の事前フィルタ用キーワード
# 誤検知を減らすため、タスク管理に特有の表現のみに絞る
_TASK_KEYWORDS = (
    # ステータス変更系（文脈が明確なもの）
    "完了", "終わった", "done", "finished", "進行中", "着手", "やってる", "wip",
    # タスク追加系（明示的なプレフィックス）
    "タスク:", "タスク：", "todo:", "todo：",
    # 日本語の典型的なタスク登録フレーズ
    "タスク追加", "タスク登録", "新規タスク",
)


# ──────────────────────────────────────────────
# イベントハンドラ
# ──────────────────────────────────────────────

@bot.event
async def on_ready():
    logger.info(f"ログイン完了: {bot.user} (ID: {bot.user.id})")
    logger.info(f"監視チャンネル: {TASK_CHANNELS}")
    # ギルドごとに同期（即時反映）
    for guild in bot.guilds:
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
        logger.info(f"スラッシュコマンドを同期しました: {guild.name}")
    # グローバル同期（反映に最大1時間かかる）
    await tree.sync()
    logger.info("グローバルスラッシュコマンドを同期しました")
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

    elif action == "list":
        tasks = get_pending_tasks()
        if not tasks:
            await message.reply("現在、未完了タスクはありません。")
        else:
            lines = [f"**未完了タスク一覧（{len(tasks)}件）**"]
            for t in tasks:
                priority_mark = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(t["priority"], "⚪")
                line = f"{priority_mark} `{t['id']}` {t['task_name']}"
                if t["assignee"]:
                    line += f"　担当: {t['assignee']}"
                if t["due_date"]:
                    line += f"　期限: {t['due_date']}"
                line += f"　[{t['status']}]"
                lines.append(line)
            await message.reply("\n".join(lines))

    # action == "none" は何もしない（雑談等はスルー）


# ──────────────────────────────────────────────
# スラッシュコマンド
# ──────────────────────────────────────────────

@tree.command(name="sync_history", description="過去のメッセージを読み込んでスプレッドシートのタスク一覧を更新します")
@app_commands.describe(days="遡る日数（デフォルト: 30日、最大: 365日）")
async def sync_history(interaction: discord.Interaction, days: int = DEFAULT_HISTORY_DAYS):
    if interaction.guild is None:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    if days < 1 or days > 365:
        await interaction.response.send_message("日数は1〜365の範囲で指定してください。", ephemeral=True)
        return

    await interaction.response.defer()

    after = datetime.now(timezone.utc) - timedelta(days=days)

    # 対象チャンネルを決定
    if TASK_CHANNELS:
        target_channels = [ch for ch in interaction.guild.text_channels if ch.name in TASK_CHANNELS]
    else:
        target_channels = list(interaction.guild.text_channels)

    if not target_channels:
        await interaction.followup.send(
            f"⚠️ 対象チャンネルが見つかりませんでした。\n"
            f"設定中の監視チャンネル: {', '.join(TASK_CHANNELS) or '（全チャンネル）'}"
        )
        return

    added = 0
    updated = 0
    skipped = 0
    total_scanned = 0
    batch_count = 0  # バッチ境界カウント用

    channel_names = ", ".join(f"#{ch.name}" for ch in target_channels)
    await interaction.followup.send(
        f"**同期を開始します**（過去{days}日間 / {channel_names}）\n"
        f"進捗は{SYNC_BATCH_SIZE}件ごとに報告します。"
    )

    # シート全行を1回だけ取得してキャッシュ（重複チェックのたびに API 呼び出ししない）
    cached_rows = await asyncio.to_thread(_get_all_rows)

    for channel in target_channels:
        try:
            async for message in channel.history(after=after, oldest_first=True, limit=None):
                if message.author.bot:
                    continue
                content = message.content.strip()
                if not content:
                    continue

                total_scanned += 1

                # ブロッキング呼び出しはスレッドで実行してイベントループを解放する
                parsed = await asyncio.to_thread(parse_message, content)
                action = parsed.get("action", "none")
                task_name = parsed.get("task_name", "")

                logger.info(
                    f"[履歴 #{channel.name}] {message.author.name}: "
                    f'"{content[:50]}" → action={action}, task="{task_name}"'
                )

                if action == "complete" and task_name:
                    if await asyncio.to_thread(update_task_status, task_name, STATUS_DONE):
                        updated += 1

                elif action == "in_progress" and task_name:
                    if await asyncio.to_thread(update_task_status, task_name, STATUS_IN_PROGRESS):
                        updated += 1

                elif action == "add" and task_name:
                    # キャッシュ内で重複チェック（API 呼び出し不要）
                    existing_row, _ = find_task_row_in_rows(task_name, cached_rows)
                    if existing_row is not None:
                        skipped += 1
                        logger.info(f"重複スキップ: '{task_name}'")
                    else:
                        task_info = {
                            "task_name": task_name,
                            "category":  parsed.get("category", ""),
                            "priority":  parsed.get("priority", "中"),
                            "due_date":  parsed.get("due_date", ""),
                            "assignee":  parsed.get("assignee", ""),
                        }
                        await asyncio.to_thread(add_task, task_info)
                        added += 1
                        # キャッシュにも追記して以降の重複チェックに反映
                        cached_rows.append([
                            "", task_info["task_name"], task_info["category"],
                            task_info["priority"], task_info["due_date"],
                            task_info["assignee"], "", "", "",
                        ])

                # バッチ境界: 進捗報告 & GC
                if total_scanned % SYNC_BATCH_SIZE == 0:
                    batch_count += 1
                    gc.collect()
                    await interaction.followup.send(
                        f"⏳ 処理中... {total_scanned}件スキャン済み"
                        f"（追加: {added}件 ／ 更新: {updated}件）"
                    )
                    await asyncio.sleep(0.5)  # GCとネットワークバッファの安定待ち

        except discord.Forbidden:
            logger.warning(f"チャンネル #{channel.name} の読み取り権限がありません")
        except Exception as e:
            logger.error(f"チャンネル #{channel.name} の処理中にエラー: {e}")

    gc.collect()
    await interaction.followup.send(
        f"✅ **同期完了**（過去{days}日間）\n"
        f"スキャン数: {total_scanned}件\n"
        f"タスク追加: {added}件 ／ ステータス更新: {updated}件 ／ 重複スキップ: {skipped}件"
    )


# ──────────────────────────────────────────────
# エントリポイント
# ──────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
