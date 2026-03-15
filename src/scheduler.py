import logging
from datetime import datetime
import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from src.config import (
    REPORT_CHANNEL,
    SPREADSHEET_URL,
    WEEKLY_REPORT_DAY,
    WEEKLY_REPORT_HOUR,
    WEEKLY_REPORT_TIMEZONE,
)
from src.sheets import get_pending_tasks
from src.ai_agent import generate_weekly_report

logger = logging.getLogger(__name__)


def setup_scheduler(bot: discord.Client) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=WEEKLY_REPORT_TIMEZONE)

    scheduler.add_job(
        func=lambda: bot.loop.create_task(_send_weekly_report(bot)),
        trigger=CronTrigger(
            day_of_week=WEEKLY_REPORT_DAY,
            hour=WEEKLY_REPORT_HOUR,
            minute=0,
            timezone=WEEKLY_REPORT_TIMEZONE,
        ),
        id="weekly_report",
        replace_existing=True,
    )

    logger.info(
        f"週次レポートスケジュール設定: 毎週{WEEKLY_REPORT_DAY} "
        f"{WEEKLY_REPORT_HOUR}:00 JST → #{REPORT_CHANNEL}"
    )
    return scheduler


async def _send_weekly_report(bot: discord.Client):
    """未完了タスクを取得してAIレポートをDiscordに投稿"""
    logger.info("週次レポート生成を開始")
    try:
        tasks = get_pending_tasks()
        today = datetime.now().strftime("%Y/%m/%d")
        report = generate_weekly_report(tasks, today, sheets_url=SPREADSHEET_URL)

        channel = discord.utils.get(bot.get_all_channels(), name=REPORT_CHANNEL)
        if channel is None:
            logger.error(f"レポートチャンネル #{REPORT_CHANNEL} が見つかりません")
            return

        await channel.send(report)
        logger.info(f"週次レポートを #{REPORT_CHANNEL} に投稿しました")
    except Exception as e:
        logger.error(f"週次レポート送信エラー: {e}")
