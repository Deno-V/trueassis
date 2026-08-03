# 字段规范（Schema）

每个条目 = 一个 `.md` 文件 = YAML front-matter（结构化字段）+ 正文（自由笔记）。

## 字段全表

| 字段 | 类型 | 必填 | 说明 |
|---|---|:--:|---|
| `id` | string | ✅ | **必须等于文件名 stem**，格式 `YYYYMMDD-slug`，创建后不可改 |
| `title` | string | ✅ | 一句话标题，动词开头更好（"梳理 X" 优于 "X 的事"） |
| `kind` | enum | ✅ | `task` `project` `recurring` `event` `idea` |
| `status` | enum | ✅ | `inbox` `next` `active` `blocked` `done` `cancelled` |
| `domain` | enum | ✅ | `work` `life` `health` `learning` `hobby` `fun` `finance` `relation` |
| `priority` | enum | ✅ | `P0` `P1` `P2` `P3`（默认 P2） |
| `due` | date | | 截止日 `YYYY-MM-DD`。**无 ddl 就留空**，不要编一个 |
| `defer` | date | | 此日期前不出现在建议中（"现在别烦我"） |
| `estimate` | string | | `2h` / `45m` / `1.5h`。用于 `next --time` 过滤 |
| `energy` | enum | | `low` `mid` `high`（默认 mid）。所需专注度 |
| `context` | list | | `[computer]` `[phone]` `[outdoor]` `[errand]` `[home]` `[office]` `[anywhere]` |
| `tags` | list | | 自由标签，如 `[data, repo]` |
| `project` | string | | 归属 project 的 id |
| `rule` | string | recurring | 重复规则，见下 |
| `last_run` | date | recurring | 上次生成实例的日期（由 CLI 维护，勿手改） |
| `remind_before` | list | | 提前提醒，如 `[3d, 1d]`，会让条目提前进入 brief 紧急区 |
| `reason` | string | cancelled | 取消理由（**必填**，用于画像学习） |
| `blocked_by` | string | blocked | 被什么阻塞（**必填**） |
| `source` | string | | 由重复任务生成的实例会记录来源定义 id |
| `created` | date | ✅ | 创建日期 |
| `updated` | date | ✅ | 最后修改日期。**停滞检测依赖它**，每次改动必须更新 |

### 类型约定

- **date**：一律 `YYYY-MM-DD`。CLI 输入可用 `today` / `+3d` / `+2w` / `fri`，落盘时会转成绝对日期。
- **list**：内联写法 `[a, b]`，空列表写 `[]` 或留空。
- **enum**：只能取 `config/config.yml` 里定义的值，`doctor` 会校验。

## 正文结构（约定，非强制）

```markdown
## 目标
做完长什么样（Definition of Done）。写不出来 = 还没想清楚。

## 下一步动作
- [ ] 具体到能立刻开始的第一步，动词开头

## 备注
链接、依赖、注意事项

## 记录
- 2026-08-03 完成：已推送到 origin/eval
- 2026-08-03 创建
```

`## 记录` 是**必须保留**的段落：CLI 的所有状态变更都会往这里追加一行（**倒序**，新的在上）。
它是这个条目的审计日志。

## 重复规则语法（`rule`）

| 语法 | 含义 | 例 |
|---|---|---|
| `daily` | 每天 | 写日报 |
| `weekday` | 工作日（周一至周五） | 检查邮件 |
| `weekly:mon` | 每周一 | 周计划 |
| `weekly:tue,thu,sat` | 每周二、四、六 | 运动 |
| `monthly:1` | 每月 1 号 | 记账对账 |
| `monthly:1,15` | 每月 1、15 号 | 双周检查 |
| `every:3d` | 距上次生成满 3 天 | 浇花 |

**幂等保证**：`recur run` 通过 `last_run` + 实例文件存在性双重判断，
同一天重复执行不会产生重复任务。可以放心挂到每日定时任务里。

**实例命名**：定义 `20260803-workout` → 实例 `20260805-workout`。
若同日撞车则加 `-r-` 前缀（`20260803-r-workout`），保证 id 全局唯一。

## 命名规范

| 对象 | 规范 | 例 |
|---|---|---|
| 条目 id / 文件名 | `YYYYMMDD-kebab-slug`，优先英文 | `20260803-finance-data-merge` |
| 日报 | `journal/daily/YYYY-MM-DD.md` | `2026-08-03.md` |
| 周报 | `journal/weekly/YYYY-Www.md` | `2026-W32.md` |
| 月报 | `journal/monthly/YYYY-MM.md` | `2026-08.md` |
| 日志 | `logs/<domain>/YYYY-MM.md` | `logs/health/2026-08.md` |
| 归档 | `archive/{done,cancelled}/YYYY/MM/<原文件名>` | `archive/done/2026/08/...` |

英文 slug 优先（跨平台、易补全、URL 安全）。中文标题若无法生成有效 ascii slug，
CLI 会退回中文 slug —— 能用，但建议手动指定 `--slug`。

## doctor 的校验项

`assis doctor` 逐条检查，**提交前必跑**：

**错误（必须修）**
- `id` ≠ 文件名 stem
- `id` 全局重复
- `status` / `domain` / `priority` 取值非法
- 日期字段格式非法
- 缺 `title`
- `recurring` 缺 `rule`
- 🔒 `private/` 下文件被 git 跟踪（隐私泄漏，含修复命令）

**警告（应该修）**
- `cancelled` 缺 `reason`
- `blocked` 缺 `blocked_by`
- `project` 指向不存在的项目
- 已关闭但未归档
- `recurring` 定义没放在 `private/recurring/`
