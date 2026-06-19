"""更好的聊天时间 — 插件入口。"""

from __future__ import annotations

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.base import BasePlugin, register_plugin
from src.kernel.concurrency import get_task_manager

from .actions.get_best_hours import GetBestHoursAction
from .actions.should_chat_now import ShouldChatNowAction
from .config import BetterChatTimeConfig
from .handlers.message_handler import MessageTimestampHandler
from .persistence.activity_store import ActivityStore
from .services.profile_service import BetterChatTimeService

logger = get_logger("bct_plugin")


@register_plugin
class BetterChatTimePlugin(BasePlugin):
    """更好的聊天时间插件。"""

    plugin_name = "better_chat_time"
    plugin_version = "0.1.0"
    plugin_author = "Lycoris"
    plugin_description = "更好的聊天时间 — 自动收集活跃时段，判断何时适合聊天"
    configs = [BetterChatTimeConfig]

    def __init__(self, config: BetterChatTimeConfig | None = None) -> None:
        super().__init__(config)
        self._activity_store = ActivityStore()

    def get_components(self) -> list[type]:
        """获取插件内所有组件类。"""
        return [
            ShouldChatNowAction,
            GetBestHoursAction,
            MessageTimestampHandler,
            BetterChatTimeService,
        ]

    async def on_plugin_loaded(self) -> None:
        """插件加载后从 DB 回填活跃时段数据。"""
        try:
            bootstrap_days = (
                self.config.general.bootstrap_days
                if self.config
                else 30
            )
        except Exception:
            bootstrap_days = 30

        # 异步执行回填，不阻塞启动
        tm = get_task_manager()
        tm.create_task(
            self._bootstrap_activity(bootstrap_days),
            name="bct_bootstrap_activity",
        )

    async def _bootstrap_activity(self, days: int) -> None:
        """从 DB 回填活跃时段数据。"""
        try:
            service = BetterChatTimeService(plugin=self)
            count = await service.bootstrap_from_db(days=days)
            logger.info(f"活跃时段 DB 回填完成: {count} 个 stream")
        except Exception as e:
            logger.warning(f"活跃时段 DB 回填失败: {e}")
