"""活跃时段 Profile 数据类型定义。"""

from __future__ import annotations

from typing import TypedDict


class HourlyCount(TypedDict):
    """24 小时分布计数，键为 "0"~"23"。"""

    __annotations__ = {str(h): int for h in range(24)}


class ActivityProfile(TypedDict):
    """单个 stream 的活跃时段 profile。

    所有字段与 JSONStore 持久化格式一一对应，
    不需要额外序列化/反序列化转换。
    """

    stream_id: str
    updated_at: float
    first_seen_at: float
    hours: HourlyCount
    weekday_hours: HourlyCount
    weekend_hours: HourlyCount
    total: int
    last_message_at: float
