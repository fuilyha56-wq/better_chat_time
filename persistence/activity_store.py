"""活跃时段数据 JSON 持久化存储。

每个 stream_id 对应一个 JSON 文件，存储该用户的消息活跃时段分布。
使用 kernel 的 JSONStore 实现文件读写，asyncio.Lock 防止并发写丢失。

特性：
- 24 小时 × 工作日/周末 分布
- first_seen_at / last_message_at 动态计算 days_covered
- LRU 锁淘汰（避免 clear() 导致并发互斥失效）
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from typing import Any

from src.app.plugin_system.api.log_api import get_logger
from src.kernel.storage import JSONStore

from .models import ActivityProfile

logger = get_logger("bct_activity_store")

_STORE_DIR = "data/better_chat_time/activity"
# LRU 锁池上限，避免高并发场景下锁对象无限增长
_MAX_LOCKS = 256


def _empty_profile(stream_id: str) -> ActivityProfile:
    """创建空的 ActivityProfile。"""
    return ActivityProfile(
        stream_id=stream_id,
        updated_at=0.0,
        first_seen_at=0.0,
        hours={str(h): 0 for h in range(24)},
        weekday_hours={str(h): 0 for h in range(24)},
        weekend_hours={str(h): 0 for h in range(24)},
        total=0,
        last_message_at=0.0,
    )


def _validate_profile(data: dict[str, Any], stream_id: str) -> ActivityProfile:
    """校验并修复 profile 数据，确保 24 槽完整。"""
    if not isinstance(data, dict):
        return _empty_profile(stream_id)

    profile = _empty_profile(stream_id)
    profile["updated_at"] = float(data.get("updated_at", 0.0) or 0.0)
    profile["first_seen_at"] = float(data.get("first_seen_at", 0.0) or 0.0)
    profile["total"] = int(data.get("total", 0) or 0)
    profile["last_message_at"] = float(data.get("last_message_at", 0.0) or 0.0)

    for key in ("hours", "weekday_hours", "weekend_hours"):
        raw = data.get(key, {})
        if isinstance(raw, dict):
            for h in range(24):
                val = raw.get(str(h), 0)
                if isinstance(val, (int, float)):
                    profile[key][str(h)] = int(val)

    return profile


class ActivityStore:
    """活跃时段持久化存储。"""

    def __init__(self) -> None:
        self._store = JSONStore(_STORE_DIR)
        self._locks: OrderedDict[str, asyncio.Lock] = OrderedDict()

    def _get_lock(self, stream_id: str) -> asyncio.Lock:
        """获取 per-stream 锁，LRU 淘汰最久未使用的。"""
        if stream_id in self._locks:
            self._locks.move_to_end(stream_id)
            return self._locks[stream_id]
        # 淘汰最旧的
        while len(self._locks) >= _MAX_LOCKS:
            self._locks.popitem(last=False)
        lock = asyncio.Lock()
        self._locks[stream_id] = lock
        return lock

    async def get_profile(self, stream_id: str) -> ActivityProfile | None:
        """获取指定 stream 的活跃时段 profile，无数据返回 None。"""
        data = await self._load_profile_data(stream_id)
        if data is None:
            return None
        return _validate_profile(data, stream_id)

    async def _load_profile_data(self, stream_id: str) -> dict[str, Any] | None:
        """读取 profile，损坏数据按不存在处理以便后续自动重建。"""
        try:
            return await self._store.load(stream_id)
        except json.JSONDecodeError as exc:
            logger.warning(f"活跃时段数据损坏，将自动重建: {stream_id}: {exc}")
            await self._store.delete(stream_id)
            return None

    async def update_profile(
        self,
        stream_id: str,
        hour: int,
        is_weekday: bool,
        timestamp: float,
    ) -> None:
        """增量更新一条消息的活跃时段记录。"""
        async with self._get_lock(stream_id):
            data = await self._load_profile_data(stream_id)
            profile = _validate_profile(data, stream_id) if data else _empty_profile(stream_id)

            h = str(max(0, min(23, hour)))
            profile["hours"][h] = profile["hours"].get(h, 0) + 1
            if is_weekday:
                profile["weekday_hours"][h] = profile["weekday_hours"].get(h, 0) + 1
            else:
                profile["weekend_hours"][h] = profile["weekend_hours"].get(h, 0) + 1
            profile["total"] += 1
            profile["last_message_at"] = max(profile["last_message_at"], timestamp)
            profile["updated_at"] = time.time()
            # 首次记录
            if profile["first_seen_at"] == 0.0:
                profile["first_seen_at"] = timestamp

            await self._store.save(stream_id, profile)

    async def save_profile(self, stream_id: str, profile: ActivityProfile) -> None:
        """整体保存一个 profile（用于 DB 回填）。"""
        async with self._get_lock(stream_id):
            profile["updated_at"] = time.time()
            await self._store.save(stream_id, profile)

    async def list_all_stream_ids(self) -> list[str]:
        """列出所有已有 profile 的 stream_id。"""
        return await self._store.list_all()

    def clear_locks(self) -> None:
        """清理所有锁资源，供插件卸载时调用。"""
        self._locks.clear()
