# 工作流（Workflows / SOP）

给人看，也给 Agent 看。Agent 执行时遵循 `AGENTS.md` §4。

---

## 每日节律

### 早上：接收简报（2 分钟）

```bash
./tools/assis recur run     # 先生成今天该做的重复任务
./tools/assis brief         # 看简报
```

对 AI 直接说：**"看下今天该干什么"**

简报的阅读顺序：
1. `⚠️ 逾期` —— 先处理这里。要么今天做掉，要么改期，要么取消。**不允许假装没看见**。
2. `📅 今天到期` —— 今天的硬承诺。
3. `▶️ 建议现在做` —— 认领 1 项，`assis start <id>`。
4. `💡 提醒` —— 系统健康度提示。

### 白天：碎片时间

```bash
./tools/assis next --energy low --time 20 --context phone
```

对 AI 说：**"我只有 20 分钟，还挺累，能干点什么"**

关键在于**诚实报告状态**。谎报精力 → 得到错误建议 → 任务失败 → 挫败感 → 放弃系统。

### 随手收集（想到什么立刻记）

```bash
./tools/assis add "标题" --domain work            # 有可能做 → 进 active
./tools/assis add "标题" --someday --kind idea    # 只是想想 → 进愿望池
./tools/assis log health "骑行 30km，膝盖有点酸"   # 事实记录，不是待办
```

对 AI 说：**"记一下：我想读《XX》，周末可能去看电影，还得处理报销"**
Agent 会一次性收进来，然后只问缺失的关键项（ddl 和优先级）。

**判断标准**：
- 「我要做 X」→ task
- 「我想要是能 X 就好了」→ idea（someday）
- 「我刚做了 X」→ log

### 晚上：日报（3 分钟）

```bash
./tools/assis journal daily
```

自动区块会填好今日完成/取消/各领域日志。你只需手写三行：

- 今天最有价值的一件事
- 卡住我的是
- 明天第一件事

这三行是画像更新的主要原料。**没有它，系统学不到任何东西。**

---

## 每周节律（建议周日晚）

```bash
./tools/assis journal weekly
```

然后逐条过一遍 `active`：

```bash
./tools/assis list --status active
```

对每一条做**四选一决策**，不允许"先放着"：

| 情况 | 动作 |
|---|---|
| 还该做，也在推进 | 保持，必要时 `edit --set due=...` |
| 已经做完了忘了标 | `assis done <id> --note "产出"` |
| 不该做了 | `assis cancel <id> --reason "..."` ← **鼓励** |
| 该做但不是现在 | `assis defer <id> --to +2w` 或 `assis someday <id>` |

再过一遍愿望池，看有没有该提上来的：

```bash
./tools/assis list --kind idea
./tools/assis edit <id> --set kind=task --set status=next --set due=+7d
```

最后更新画像：

```bash
./tools/assis profile --append "周三晚固定加班，不要安排学习任务"
```

对 AI 说：**"陪我做周复盘"**

---

## 月度节律

```bash
./tools/assis journal monthly
./tools/assis archive        # 清理已关闭条目
./tools/assis doctor         # 数据体检
```

重点检查：**当期重心还对不对**。如果一个月里重心相关任务的完成率很低，
说明重心定错了，或者被杂事挤掉了 —— 这两种情况的处理方式完全不同，值得想清楚。

---

## 场景速查

### 新开一个长期项目

```bash
./tools/assis add "金融数据平台" --kind project --domain work --priority P1 --slug fin-platform
# 立刻拆出第一个可执行子任务 —— 否则项目就是空话
./tools/assis add "梳理数据源与字段映射" --domain work --project 20260803-fin-platform --due +4d --estimate 2h --energy high --context computer
```

**规则：任何 project 创建后必须立刻有至少一个子任务。** brief 会盯着这件事。

### 建一个重复任务

```bash
./tools/assis recur add "运动" --rule weekly:tue,thu,sat --domain health --estimate 1h --energy high --context outdoor
./tools/assis recur run                          # 立刻生成本期实例
./tools/assis recur pause 20260803-workout       # 暂停（旅行期间）
./tools/assis recur pause 20260803-workout --on  # 恢复
```

重复任务的实例**该跳过就跳过** —— 直接 `cancel --reason "出差"`，
不影响后续生成。不要为了"连续打卡"而虚报完成。

### 有固定时间点的事（电影/会议/出发）

```bash
./tools/assis add "骑行 北京→天津" --kind event --domain hobby --due 2026-08-08 \
  --estimate 8h --energy high --context outdoor --remind 3d,1d
```

`--remind 3d,1d` 让它在 3 天前就进入 brief 的紧急区，给准备留时间。

### 被别人卡住了

```bash
./tools/assis block <id> --by "等 A 提供数据字典"
# 解除后
./tools/assis edit <id> --set status=active --note "已拿到字典"
```

`blocked` 的条目不进建议区（避免你反复看到做不了的事），但会在 brief 单独列出提醒你去催。

### 找东西

```bash
./tools/assis list --grep 金融                 # 全文搜
./tools/assis list --domain work --due-in 7    # 一周内的工作
./tools/assis list --archive --grep webfetch   # 翻历史（含归档）
./tools/assis show finance                     # id 前缀模糊匹配
```

---

## 自动化（主动提醒）

### CodeBuddy

用 automation 注册三个定时任务：

| 时间 | 提示词 |
|---|---|
| 每日 09:00 | 跑 `./tools/assis recur run` 和 `./tools/assis brief`，把逾期项与今日建议汇报给我 |
| 每日 21:30 | 跑 `./tools/assis journal daily`，提醒我补写复盘三行 |
| 每周日 20:00 | 按 `AGENTS.md` §4.4 陪我做周复盘 |

### 其他工具 / 系统级（macOS launchd 或 cron）

一键安装（会挂 4 条 cron：重复任务生成、到期通知、日报、周报）：

```bash
bash tools/install-reminders.sh --dry-run   # 先看会写什么
bash tools/install-reminders.sh             # 安装
bash tools/install-reminders.sh --uninstall # 卸载
```

macOS 需在「系统设置 → 隐私与安全性 → 完全磁盘访问权限」中授权 cron。

手动配置的话：

```bash
# crontab -e
0 9 * * *  cd ~/Desktop/trueassis && /usr/bin/python3 tools/assis recur run >> /tmp/assis.log 2>&1
5 9 * * *  cd ~/Desktop/trueassis && /usr/bin/python3 tools/assis brief >> /tmp/assis-brief.log 2>&1
0 22 * * * cd ~/Desktop/trueassis && /usr/bin/python3 tools/assis journal daily >> /tmp/assis.log 2>&1
```

配合 macOS 桌面通知（可选）：

```bash
0 9 * * * cd ~/Desktop/trueassis && n=$(/usr/bin/python3 tools/assis brief --json | /usr/bin/python3 -c 'import json,sys;d=json.load(sys.stdin);print(len(d["overdue"])+len(d["today"]))') && [ "$n" -gt 0 ] && osascript -e "display notification \"今天有 $n 项待办\" with title \"trueassis\""
```

---

## 反模式（不要这样用）

| ❌ 反模式 | 后果 | ✅ 正确做法 |
|---|---|---|
| 把所有想法都放进 `active` | 列表变噪音，你会停止打开它 | 只把承诺要做的放 active，其余 `--someday` |
| 给每件事都编一个 ddl | ddl 失去意义，逾期区永远爆红 | 无 ddl 就留空，靠停滞检测兜底 |
| 从不 cancel | 变成负债清单，打开就有压力 | 每周至少放弃一件事 |
| 谎报精力/时间 | 得到错误建议，任务失败 | 诚实报告，系统才有用 |
| 只用 CLI 不写复盘 | 画像永远空，建议永远泛泛 | 每天三行复盘 |
| 手改 `id` 或 `last_run` | 破坏引用与幂等 | 用 CLI，或先跑 `doctor` |
| 把 `private/` 推公共远端 | 隐私泄漏 | 见 `sync.md` |
