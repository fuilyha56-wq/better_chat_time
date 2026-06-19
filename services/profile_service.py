"""更好的聊天时间 Service 实现。

纯后台 Service：暴露活跃度判断、最佳时段推荐、DB 回填等 API，
供 NFC ProactiveThinker 等系统组件通过 ServiceManager 调用。
"""

from __future__ import annotations

import time
from typing import Any

from src.app.plugin_system.api.log_api import get_logger
from src.core.components.base.service import BaseService
from src.kernel.db import QueryBuilder

logger = get_logger("better_chat_time_service")

# 相邻小时平滑权重：[前一小时, 当前小时, 后一小时]
_SMOOTH_WEIGHTS = (0.2, 0.6, 0.2)


class BetterChatTimeService(BaseService):
    """更好的聊天时间服务。"""

    service_name = "better_chat_time"
    service_description = "更好的聊天时间 — 活跃度判断与最佳时段推荐"
    version = "0.1.0"

    def _get_activity_store(self):
        """获取 ActivityStore 实例。"""
        return self.plugin._activity_store  # type: ignore[attr-defined]

    # ──────────────────────────────────────────────
    # 核心 API
    # ──────────────────────────────────────────────

    async def is_good_time(self, stream_id: str) -> float:
        """判断当前是否适合聊天。

        Returns:
            float 0.0~1.0 置信度。
            1.0 = 非常适合，0.0 = 非常不适合。
            NFC ProactiveThinker 可直接拿来当概率乘数。
        """
        store = self._get_activity_store()
        profile = await store.get_profile(stream_id)

        if profile is None or profile["total"] == 0:
            return 0.5  # 无数据时不做判断，返回中性

        now = time.time()
        lt = time.localtime(now)
        current_hour = lt.tm_hour
        is_weekday = lt.tm_wday < 5

        # 1. 基于历史分布的活跃度（带相邻小时平滑）
        hour_score = self._calc_hour_score(profile, current_hour, is_weekday)

        # 2. last_message_at 近期消息强信号
        recency_boost = self._calc_recency_boost(profile, now)

        # 3. 连续静默降级
        silence_penalty = self._calc_silence_penalty(profile, now)

        # 综合
        score = hour_score + recency_boost - silence_penalty
        return max(0.0, min(1.0, score))

    async def get_best_hours(
        self, stream_id: str, top_n: int = 5, for_today: bool = True
    ) -> list[dict[str, Any]]:
        """获取最佳聊天时段。

        Args:
            stream_id: 目标 stream
            top_n: 返回前 N 个时段
            for_today: True 时只返回当天类型（工作日/周末）的数据

        Returns:
            [{"hour": int, "score": float, "count": int}, ...]
        """
        store = self._get_activity_store()
        profile = await store.get_profile(stream_id)

        if profile is None or profile["total"] == 0:
            return []

        is_weekday = time.localtime().tm_wday < 5
        hours_data = self._get_relevant_hours(profile, is_weekday if for_today else None)
        total = sum(hours_data.values())
        if total == 0:
            return []

        avg = total / 24.0
        results = []
        for h in range(24):
            count = hours_data.get(str(h), 0)
            score = count / avg if avg > 0 else 0.0
            results.append({"hour": h, "score": round(score, 2), "count": count})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_n]

    async def get_activity_summary(self, stream_id: str) -> dict[str, Any] | None:
        """获取活跃度概览信息。

        Returns:
            dict 包含 total, days_covered, last_message_at, is_good_time 等。
            无数据返回 None。
        """
        store = self._get_activity_store()
        profile = await store.get_profile(stream_id)
        if profile is None or profile["total"] == 0:
            return None

        now = time.time()
        first_seen = profile.get("first_seen_at", 0.0)
        days_covered = max(1, int((now - first_seen) / 86400)) if first_seen > 0 else 0

        score = await self.is_good_time(stream_id)

        return {
            "total": profile["total"],
            "days_covered": days_covered,
            "last_message_at": profile["last_message_at"],
            "silence_hours": (now - profile["last_message_at"]) / 3600 if profile["last_message_at"] > 0 else None,
            "current_score": round(score, 3),
        }

    # ──────────────────────────────────────────────
    # DB 回填
    # ──────────────────────────────────────────────

    async def bootstrap_from_db(
        self, stream_ids: list[str] | None = None, days: int = 30
    ) -> int:
        """从 DB 回填活跃时段数据。

        Args:
            stream_ids: 要回填的 stream 列表。None 表示自动发现。
            days: 回溯天数。

        Returns:
            成功回填的 stream 数量。
        """
        from src.core.models.sql_alchemy import Messages

        if stream_ids is None:
            stream_ids = await self._discover_streams()

        store = self._get_activity_store()
        existing = await store.list_all_stream_ids()
        now = time.time()
        start_time = now - days * 86400
        decay_days = self._get_config_value("activity_decay_days", 90)

        count = 0
        for sid in stream_ids:
            # 已有且未过期的跳过
            if sid in existing:
                profile = await store.get_profile(sid)
                if profile and profile["total"] > 0:
                    if now - profile.get("updated_at", 0) < decay_days * 86400:
                        continue

            # 从 DB 查询
            hourly = [0] * 24
            weekday_hourly = [0] * 24
            weekend_hourly = [0] * 24
            total = 0
            first_ts = 0.0
            last_ts = 0.0

            async for row in QueryBuilder(Messages).filter(
                stream_id=sid,
                time__gte=start_time,
                time__lt=now,
            ).iter_all(batch_size=1000, as_dict=True):
                ts = row.get("time", 0)
                if not isinstance(ts, (int, float)) or ts <= 0:
                    continue
                total += 1
                lt = time.localtime(float(ts))
                hour = lt.tm_hour
                hourly[hour] += 1
                if lt.tm_wday < 5:
                    weekday_hourly[hour] += 1
                else:
                    weekend_hourly[hour] += 1
                if first_ts == 0.0 or float(ts) < first_ts:
                    first_ts = float(ts)
                if float(ts) > last_ts:
                    last_ts = float(ts)

            if total > 0:
                profile = {
                    "stream_id": sid,
                    "updated_at": now,
                    "first_seen_at": first_ts,
                    "hours": {str(h): hourly[h] for h in range(24)},
                    "weekday_hours": {str(h): weekday_hourly[h] for h in range(24)},
                    "weekend_hours": {str(h): weekend_hourly[h] for h in range(24)},
                    "total": total,
                    "last_message_at": last_ts,
                }
                await store.save_profile(sid, profile)
                count += 1

        logger.info(f"DB 回填完成: {count}/{len(stream_ids)} 个 stream 有数据")
        return count

    async def _discover_streams(self) -> list[str]:
        """从 DB 发现所有 stream_id（群聊 + 私聊）。"""
        try:
            from src.core.models.sql_alchemy import ChatStreams
            records = await QueryBuilder(ChatStreams).all(as_dict=True)
            return [r["stream_id"] for r in records if r.get("stream_id")]
        except Exception as e:
            logger.warning(f"发现 stream 列表失败: {e}")
            return []

    # ──────────────────────────────────────────────
    # 内部计算方法
    # ──────────────────────────────────────────────

    def _calc_hour_score(
        self, profile: dict[str, Any], current_hour: int, is_weekday: bool
    ) -> float:
        """计算基于历史分布的小时活跃度评分（0~1），带相邻小时平滑。"""
        hours_data = self._get_relevant_hours(profile, is_weekday)
        total = sum(hours_data.values())
        if total == 0:
            return 0.5

        # 相邻小时平滑
        prev_h = (current_hour - 1) % 24
        next_h = (current_hour + 1) % 24
        smoothed_count = (
            _SMOOTH_WEIGHTS[0] * hours_data.get(str(prev_h), 0)
            + _SMOOTH_WEIGHTS[1] * hours_data.get(str(current_hour), 0)
            + _SMOOTH_WEIGHTS[2] * hours_data.get(str(next_h), 0)
        )

        # 归一化：相对于均匀分布的比值
        avg = total / 24.0
        if avg == 0:
            return 0.5

        ratio = smoothed_count / avg
        # ratio 0 -> score 0, ratio 1 -> score 0.5, ratio 2+ -> score ~1.0
        # 使用 sigmoid-like 映射
        score = min(1.0, ratio / 2.0)
        return score

    def _calc_recency_boost(self, profile: dict[str, Any], now: float) -> float:
        """近期消息加成：用户刚发过消息说明在线。"""
        last_msg = profile.get("last_message_at", 0.0)
        if last_msg <= 0:
            return 0.0

        elapsed_minutes = (now - last_msg) / 60.0
        if elapsed_minutes < 10:
            return 0.3  # 10 分钟内刚说过话，强加成
        if elapsed_minutes < 30:
            return 0.15
        if elapsed_minutes < 60:
            return 0.05
        return 0.0

    def _calc_silence_penalty(self, profile: dict[str, Any], now: float) -> float:
        """连续静默降级：长时间无消息说明可能不在。"""
        last_msg = profile.get("last_message_at", 0.0)
        if last_msg <= 0:
            return 0.0

        silence_days = (now - last_msg) / 86400.0
        if silence_days < 1:
            return 0.0
        if silence_days < 3:
            return 0.1
        if silence_days < 7:
            return 0.2
        return 0.3  # 超过一周无消息，大幅降低

    def _get_relevant_hours(
        self, profile: dict[str, Any], is_weekday: bool | None
    ) -> dict[str, int]:
        """获取相关的小时分布数据。"""
        if is_weekday is None:
            return profile.get("hours", {})
        if is_weekday:
            return profile.get("weekday_hours", {})
        return profile.get("weekend_hours", {})

    def _get_config_value(self, key: str, default: Any) -> Any:
        """安全读取配置值。"""
        try:
            from ..config import BetterChatTimeConfig
            config = self.plugin.config  # type: ignore[attr-defined]
            if isinstance(config, BetterChatTimeConfig):
                return getattr(config.general, key, default)
        except Exception:
            pass
        return default
