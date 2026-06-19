# Better Chat Time / 更好的聊天时间

> Neo-MoFox 插件 — 自动收集用户活跃时段，判断何时适合聊天

---

## 概述

Better Chat Time（BCT）是一个后台 Service 插件，核心能力：

- **系统自动收集** — 订阅 ON_MESSAGE_RECEIVED 事件，每条用户消息到达时自动记录时间戳，不需要 LLM 介入
- **启动时 DB 回填** — 插件加载时从数据库回填历史活跃数据，无需从零积累
- **is_good_time API** — 返回 0.0~1.0 置信度，供 ProactiveThinker 等系统组件直接调用
- **should_chat_now / get_best_hours** — 两个可选 LLM tool，装了就自动出现在 chatter 上下文中

BCT 不需要 LLM 来运行。数据收集、存储、判断全部自动完成。LLM tool 是可选的消费端。

---

## 架构

```
启动 → on_plugin_loaded()
  └─ 异步 bootstrap: 扫描 DB → 写入 ActivityStore

运行时 → ON_MESSAGE_RECEIVED
  └─ MessageTimestampHandler → ActivityStore.update_profile()

Service API（系统调用）
  ├─ is_good_time(stream_id) → float 0~1
  ├─ get_best_hours(stream_id) → top-N 时段
  └─ get_activity_summary(stream_id) → 概览

LLM Tool（可选）
  ├─ should_chat_now → 适合/谨慎/不适合
  └─ get_best_hours → 最佳时段推荐
```

### 评分逻辑

`is_good_time()` 综合三个因子：

1. **历史小时活跃度**（0~0.5）— 当前小时在 weekday/weekend 分布中的占比，带相邻小时平滑（前后各 ±1 小时加权）
2. **近期消息加成**（0~0.3）— 10分钟内发过消息 +0.3，30分钟内 +0.15，1小时内 +0.05
3. **连续静默降级**（0~0.3）— 1天无消息 -0.1，3天 -0.2，7天+ -0.3

### 数据存储

- `data/better_chat_time/activity/{stream_id}.json`
- 格式：

```json
{
  "stream_id": "...",
  "first_seen_at": 1700000000.0,
  "last_message_at": 1700100000.0,
  "updated_at": 1700100000.0,
  "total": 1234,
  "hours": {"0": 12, "1": 5, ...},
  "weekday_hours": {"0": 8, "1": 3, ...},
  "weekend_hours": {"0": 4, "1": 2, ...}
}
```

---

## 配置

配置文件路径：`config/plugins/better_chat_time/config.toml`

```toml
[general]
enabled = true
bootstrap_days = 30        # 启动时从 DB 回填的历史天数
activity_decay_days = 90   # 超过此天数未更新的 profile 重新回填
```

---

## Service API

其他插件通过 ServiceManager 调用：

```python
service = ServiceManager.get_service("better_chat_time:service:better_chat_time")

# 判断是否适合聊天（返回 0.0~1.0）
score = await service.is_good_time(stream_id)

# 获取最佳时段
best = await service.get_best_hours(stream_id, top_n=5)
# [{"hour": 20, "score": 2.1, "count": 89}, ...]

# 活跃度概览
summary = await service.get_activity_summary(stream_id)
# {"total": 1234, "days_covered": 45, "silence_hours": 3.2, "current_score": 0.72}

# 手动触发 DB 回填
count = await service.bootstrap_from_db(days=30)
```

---

## 与 NFC 共存

- BCT 的 Action 声明 `chatter_allow = ["neo_fatum_chatter"]`，安装即可见，卸载即消失
- NFC 代码无需修改
- 未来 ProactiveThinker 可通过 config 指定 BCT Service 签名来接入（当前未实现）

---

## 安装

```bash
mpdt market install better_chat_time
```

---

## 许可证

AGPL-3.0
