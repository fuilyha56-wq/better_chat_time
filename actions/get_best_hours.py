"""查询对方最佳聊天时段。

返回活跃度最高的几个小时，帮助 LLM 在 schedule_proactive 时选择时间。
"""

from __future__ import annotations

import time
from typing import Annotated

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.base import BaseAction

logger = get_logger("bct_get_best_hours")


class GetBestHoursAction(BaseAction):
    """查询对方最佳聊天时段。"""

    name = "get_best_hours"
    description = (
        "查询对方最适合聊天的时段。基于系统自动收集的活跃数据，"
        "返回活跃度最高的几个小时。"
        "适合在预约下次主动聊天（schedule_proactive）时参考。"
    )
    chatter_allow: list[str] = ["neo_fatum_chatter"]
    associated_types = ["text"]

    async def execute(
        self,
        top_n: Annotated[
            int,
            "返回前几个最佳时段，默认5。",
        ] = 5,
        **_extra,
    ) -> tuple[bool, str]:
        """查询最佳聊天时段。"""
        stream_id = self.chat_stream.stream_id

        # 延迟导入避免循环依赖：action → service → plugin → action
        from ..services.profile_service import BetterChatTimeService
        service = BetterChatTimeService(plugin=self.plugin)  # type: ignore[arg-type]  # BasePlugin → BetterChatTimePlugin，框架限制

        top_n = max(1, min(top_n, 10))
        best = await service.get_best_hours(stream_id, top_n=top_n)

        if not best:
            return True, "数据不足，无法推荐最佳时段。"

        is_weekday = time.localtime().tm_wday < 5
        day_type = "工作日" if is_weekday else "周末"

        lines = [f"对方{day_type}最活跃的时段："]
        for item in best:
            hour = item["hour"]
            score = item["score"]
            count = item["count"]
            # score > 1.0 表示高于平均
            if score >= 1.5:
                tag = "★★"
            elif score >= 1.0:
                tag = "★"
            else:
                tag = "·"
            lines.append(f"  {tag} {hour:02d}时 (活跃指数 {score:.1f}, {count}条消息)")

        return True, "\n".join(lines)
