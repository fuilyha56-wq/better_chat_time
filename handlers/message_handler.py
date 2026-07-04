"""自动记录用户消息时间戳到活跃时段。

订阅 ON_MESSAGE_RECEIVED 事件，每条用户消息到达时
自动更新 ActivityStore，无需 LLM 介入。
"""

from __future__ import annotations

import time
from typing import Any

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.base import BaseEventHandler
from src.core.components.types import EventType
from src.kernel.event import EventDecision

from ..persistence.activity_store import ActivityStore

logger = get_logger("bct_message_handler")


class MessageTimestampHandler(BaseEventHandler):
    """自动记录用户消息时间戳。"""

    handler_name = "message_timestamp"
    handler_description = "自动记录每条用户消息的时间戳到活跃时段"
    weight = 0
    intercept_message = False
    init_subscribe = [EventType.ON_MESSAGE_RECEIVED]

    async def execute(
        self, event_name: str, params: dict[str, Any]
    ) -> tuple[EventDecision, dict[str, Any]]:
        """收到消息时自动记录活跃时段。"""
        message = params.get("message")
        if message is None:
            return EventDecision.PASS, params

        # 提取关键字段
        stream_id = getattr(message, "stream_id", None)
        timestamp = getattr(message, "time", None)

        if not stream_id or timestamp is None:
            return EventDecision.PASS, params

        # 跳过 bot 自己发的消息（sender_role == "bot"）
        sender_role = getattr(message, "sender_role", "")
        if sender_role == "bot":
            return EventDecision.PASS, params

        try:
            ts = float(timestamp)
            lt = time.localtime(ts)
            hour = lt.tm_hour
            is_weekday = lt.tm_wday < 5

            store: ActivityStore = self.plugin.activity_store
            await store.update_profile(stream_id, hour, is_weekday, ts)
        except Exception as e:
            logger.debug(f"记录活跃时段失败: {e}")

        return EventDecision.SUCCESS, params
