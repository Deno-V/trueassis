# 同步策略（Sync）

核心原则：**框架推远端，个人数据留本地。**

```
┌─────────────────────────────────────────────────────────┐
│  trueassis/  （主仓库 → 可推公共/私有远端）              │
│    AGENTS.md  docs/  templates/  tools/  config/         │
│    .gitignore  README.md  CLAUDE.md  .codebuddy/ ...     │
│                                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │ private/   ← 被 .gitignore 忽略，主仓库看不见它    │  │
│  │   可选：自己是一个独立的 git 仓库 → 私有远端       │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

`private/` 被根 `.gitignore` 忽略，因此主仓库**永远不会**带上个人数据。
`assis doctor` 会主动检查 `git ls-files private` —— 一旦有泄漏立刻报错并给修复命令。

---

## 方案 A：只同步框架（最简，推荐起步）

个人数据完全不进任何远端，仅靠本地备份（Time Machine / iCloud 等）。

```bash
cd ~/Desktop/trueassis
git init && git add . && git commit -m "feat: trueassis 初始化"
git remote add origin <你的仓库地址>
git push -u origin main
```

好处：零泄漏风险。代价：换机器要重新录数据。

---

## 方案 B：private 挂独立私有仓库（推荐长期使用）

给 `private/` 单独 `git init`，指向一个**私有**远端。两个仓库互不干扰
（主仓库忽略 `private/`，`private/` 自己的 `.git` 也不会被主仓库看见）。

```bash
cd ~/Desktop/trueassis/private
git init
git add .
git commit -m "data: 初始化个人数据"
git remote add origin git@github.com:<你>/trueassis-private.git   # 必须是 private 仓库
git push -u origin main
```

日常同步（个人数据变更频繁，建议每天一次）：

```bash
cd ~/Desktop/trueassis/private && git add -A && git commit -m "data: $(date +%F)" && git push
```

可以做成 alias：

```bash
# ~/.zshrc
alias assis='python3 ~/Desktop/trueassis/tools/assis'
alias assis-sync='cd ~/Desktop/trueassis/private && git add -A && git commit -m "data: $(date +%F)" && git push && cd -'
```

⚠️ 确认远端是 **private** 仓库。这里面有你的健康、财务、人际关系记录。

### 换机器恢复

```bash
git clone <框架仓库> trueassis
cd trueassis
git clone <私有数据仓库> private
python3 tools/assis doctor    # 验证数据完整
python3 tools/assis brief
```

---

## 方案 C：git submodule（不推荐）

技术上可行，但 submodule 的操作复杂度会让 AI Agent 频繁出错
（detached HEAD、忘记 `--recurse-submodules`、嵌套提交顺序）。
本系统的目标是让 Agent 顺畅操作，方案 B 更稳。

---

## 远端放什么模版

如果你想让别人复用这个框架（或者你自己换个身份重新开始），
可以在远端提供**脱敏示例**，放在 `examples/` 而不是 `private/`：

```
examples/
  profile.example.md      填好的画像样例（虚构人物）
  task.example.md         一个完整任务的样子
  daily.example.md        一份写好的日报
```

原则：`examples/` 里**不能有任何真实个人信息**。
真实数据永远只在 `private/`。

---

## 提交信息约定

| 前缀 | 用途 | 仓库 |
|---|---|---|
| `feat:` | 新增框架能力（CLI 命令、模版） | 主仓库 |
| `fix:` | 修 bug | 主仓库 |
| `docs:` | 文档 | 主仓库 |
| `chore:` | 配置、杂项 | 主仓库 |
| `data:` | 个人数据变更 | **仅 private 仓库** |

`data:` 前缀绝不应该出现在主仓库的提交历史里 —— 如果出现了，说明有泄漏。

---

## Agent 红线

写给 AI Agent，也提醒人类：

1. **禁止** `git add -f private/`
2. **禁止**修改 `.gitignore` 中 `private/` 的忽略规则
3. **禁止**未经明确指令 push / 建远端 / 改 remote
4. 提交前**必须**跑 `./tools/assis doctor`
5. 主仓库提交时若发现 `private/` 出现在 staged 列表 → **立即停止并报告**

修复泄漏：

```bash
git rm -r --cached private
git commit -m "fix: 移除误入索引的个人数据"
# 若已 push，需要清理历史（git filter-repo）并轮换任何暴露的凭据
```
