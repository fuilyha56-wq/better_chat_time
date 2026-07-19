"""判断当前是否适合和对方聊天。

基于 BetterChatTimeService 的 is_good_time() 返回结论。
数据由系统自动收集，LLM 只需调用即可获得判断。
"""

from __future__ import annotations

import time

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.base import BaseAction

from ..utils import format_hour_range

logger = get_logger("bct_should_chat_now")


class ShouldChatNowAction(BaseAction):
    """判断当前是否适合和对方聊天。"""

    name = "should_chat_now"
    description = (
        "判断当前是否适合和对方聊天。基于系统自动收集的活跃时段数据，"
        "返回「适合」「谨慎」「不适合」的结论。"
        "适合在想主动发起对话、预约下次聊天时间等场景下使用。"
    )
    chatter_allow: list[str] = ["neo_fatum_chatter"]
    associated_types = ["text"]

    async def execute(self, **_extra) -> tuple[bool, str]:
        """判断当前是否适合聊天。"""
        stream_id = self.chat_stream.stream_id

        # 延迟导入避免循环依赖：action → service → plugin → action
        from ..services.profile_service import BetterChatTimeService
        service = BetterChatTimeService(plugin=self.plugin)  # type: ignore[arg-type]  # BasePlugin → BetterChatTimePlugin，框架限制

        # 获取评分
        score = await service.is_good_time(stream_id)

        # 获取最佳时段
        best = await service.get_best_hours(stream_id, top_n=3)

        # 获取概览
        summary = await service.get_activity_summary(stream_id)

        if summary is None:
            return True, "数据不足，无法判断活跃时段，需要更多消息积累。"

        now_hour = time.localtime().tm_hour

        # 判断等级
        if score >= 0.6:
            level = "适合"
            reason = f"对方当前时段（{now_hour}时）活跃度较高"
        elif score >= 0.3:
            level = "谨慎"
            reason = f"对方当前时段（{now_hour}时）活跃度一般"
        else:
            level = "不适合"
            reason = f"对方当前时段（{now_hour}时）活跃度很低"

        # 补充静默信息
        silence_hours = summary.get("silence_hours")
        if silence_hours is not None and silence_hours > 24:
            reason += f"，且已 {int(silence_hours / 24)} 天无消息"
        elif silence_hours is not None and silence_hours < 1:
            reason += "，且近期刚发过消息"

        lines = [f"{level} — {reason}（置信度 {score:.0%}）"]

        # 推荐时段
        if best and level != "适合":
            peak_hours = [item["hour"] for item in best if item["score"] > 1.0]
            if peak_hours:
                lines.append(f"推荐时段: {format_hour_range(peak_hours)}")

        return True, "\n".join(lines)
