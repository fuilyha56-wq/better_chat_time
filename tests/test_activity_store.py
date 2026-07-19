"""better_chat_time 活跃数据损坏恢复测试。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from plugins.better_chat_time.persistence.activity_store import ActivityStore


class BrokenThenWritableStore:
    """首次读取损坏、允许后续保存的最小 JSONStore 替身。"""

    def __init__(self) -> None:
        self.saved: dict[str, dict[str, Any]] = {}
        self.deleted: list[str] = []

    async def load(self, name: str) -> dict[str, Any] | None:
        """模拟空 JSON 文件导致的解析失败。"""
        raise json.JSONDecodeError("Expecting value", "", 0)

    async def save(self, name: str, data: dict[str, Any]) -> None:
        """记录重建后的 profile。"""
        self.saved[name] = data

    async def delete(self, name: str) -> bool:
        """记录损坏 profile 的清理。"""
        self.deleted.append(name)
        return True


@pytest.mark.asyncio
async def test_get_profile_treats_broken_json_as_missing() -> None:
    """损坏的单个 profile 不应中止 DB 回填。"""
    activity_store = ActivityStore()
    broken_store = BrokenThenWritableStore()
    activity_store._store = broken_store  # type: ignore[assignment]

    assert await activity_store.get_profile("stream-1") is None
    assert broken_store.deleted == ["stream-1"]


@pytest.mark.asyncio
async def test_update_profile_rebuilds_broken_json() -> None:
    """收到新消息时应从损坏 profile 自动重建。"""
    activity_store = ActivityStore()
    broken_store = BrokenThenWritableStore()
    activity_store._store = broken_store  # type: ignore[assignment]

    await activity_store.update_profile(
        stream_id="stream-1",
        hour=18,
        is_weekday=True,
        timestamp=1000.0,
    )

    profile = broken_store.saved["stream-1"]
    assert profile["total"] == 1
    assert profile["hours"]["18"] == 1
    assert profile["weekday_hours"]["18"] == 1
