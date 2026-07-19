"""更好的聊天时间配置定义。"""

from __future__ import annotations

from typing import ClassVar

from src.app.plugin_system.base import BaseConfig, Field, SectionBase, config_section


class BetterChatTimeConfig(BaseConfig):
    """更好的聊天时间配置。"""

    name: ClassVar[str] = "config"
    description: ClassVar[str] = "更好的聊天时间配置"

    @config_section("general")
    class GeneralSection(SectionBase):
        """基础配置。"""

        enabled: bool = Field(default=True, description="是否启用")
        bootstrap_days: int = Field(
            default=30,
            description="启动时从 DB 回填活跃数据的历史天数",
        )
        activity_decay_days: int = Field(
            default=90,
            description="超过此天数未更新的 profile 自动从 DB 刷新",
        )

    general: GeneralSection = Field(default_factory=GeneralSection)
