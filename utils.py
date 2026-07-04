"""BCT 插件通用工具函数。"""

from __future__ import annotations


def format_hour_range(hours: list[int]) -> str:
    """将小时列表格式化为连续区间描述。

    Examples:
        [8, 9, 10, 14, 15] → "8-10时, 14-15时"
        [8] → "8时"
    """
    if not hours:
        return ""
    sorted_h = sorted(hours)
    ranges: list[str] = []
    start = sorted_h[0]
    end = sorted_h[0]
    for h in sorted_h[1:]:
        if h == end + 1:
            end = h
        else:
            ranges.append(f"{start}时" if start == end else f"{start}-{end}时")
            start = h
            end = h
    ranges.append(f"{start}时" if start == end else f"{start}-{end}时")
    return ", ".join(ranges)
