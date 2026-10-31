# 阶段 2：最小接入 Implementation Plan

> **For agentic workers:** 使用 writing-for-agents、test-driven-development；按下面顺序执行，技能行为和完成代码分别做独立审查。用户已确认基线并授权继续实施。

**Goal:** 交付可预览、可重试和可恢复的本地安装器，一份跨工具任务路由，以及使用方工程可维护的配置。

**Architecture:** Python 3.9+ 标准库 CLI 读取本仓库资源。两端共用 `.agents/skills/personal-dev/`；根 AGENTS 仅追加管理区块，Cursor 新建单独规则指针。工程配置由用户维护，模板更新不覆盖它。原始 init/doctor/recover 不联网，也不执行配置中的验证命令；后续按工程联网检查与升级见 [更新扩展](updates.md)。

**Tech Stack:** Python 标准库、unittest、JSON、Markdown、Cursor MDC。

## 文件与职责

- `scripts/pda.py`：init（默认预览，--apply 写入）、doctor（只读状态）、recover（恢复最近一次写入）。
- `scripts/pda/config.py`：配置默认值、结构校验和事实发现。
- `scripts/pda/install.py`：文件清单、管理区块、冲突检查和差异。
- `scripts/pda/transaction.py`：路径保护、原子写、恢复日志和并发锁。
- `templates/project.json`、`templates/project-guide.md`：使用方配置和说明。
- `adapters/cursor/personal-dev.mdc`：条件入口。
- `skills/personal-dev/SKILL.md` 及 `references/`：路由、角色、按任务加载的流程。
- `profiles/core.json`：固定上游来源及候选技能；本阶段仅记录/检查，不下载安装上游。
- `tests/`：真实临时目录中的 CLI 集成测试、故障恢复及行为案例。

## 管理与恢复约定

安装目标必须是已有目录。受管文件的摘要保存在可提交的 `docs/agents/personal-dev.lock.json`；工程自有配置 `docs/agents/project.json` 只在缺失时生成。AGENTS 和 .gitignore 仅管理标记区，区外逐字保留。其他已存在同名内容拒绝收编或覆盖。

默认显示文件动作和 unified diff，零写入；--apply 也先展示同样差异。冲突在任何写入前报错。用户更改受管文件后，升级保留现场，说明需人工合并。不提供 force 覆盖。

写入前将原始/目标字节及权限写入 `.local/agent/install/transaction.json`；每文件原子替换。异常保留日志，后续 init 拒绝继续直到 recover。recover 预检所有文件，只恢复仍等于原始或本次写入内容的文件；用户的后续修改导致拒绝整次恢复。恢复日志标记完成，允许再次安装。恢复不删除既有目录，只还原本次文件。

拒绝目标内符号链接路径、目录替代文件和路径穿越；锁用于避免本安装器并发写入。不承诺与任意编辑器并发修改或断电的跨文件原子性。

## 执行任务

- [x] 1. 编写 CLI 测试，确认缺失入口导致预期失败；覆盖预览、干净安装、重复执行、保留原规则/配置、冲突零写入。
- [x] 2. 实现配置、模板、原始路由与两端入口；先做无技能基线，再做带技能的独立行为案例。
- [x] 3. 实现事务与安装器；测试中途写失败、恢复、用户后改拒绝恢复、符号链接、跨克隆清单、更新与权限保护。
- [x] 4. 增加 doctor，分别报告本地存在、来源匹配、外部授权与连接未验证；用户确认的 Drone 状态仅沿用输入。
- [x] 5. 在临时空白工程和 zkxw 隔离试点验证安装/重试/恢复；不改 zkxw 主目录既有 MCP 和 Drone。
- [x] 6. 完成静态检查、OpenSpec 校验、独立审查，更新成熟度和使用说明，提交并推送现有草稿 PR。

## 明确边界

此阶段提供最小接入，不等于全部上游自动安装或场景验收。新工程的技术选型、Gitea 接通、所选打包方案验证（如适用）、MCP 授权、真实 Bug/功能任务、Cursor 实际会话行为和夜间调度各自留下待验证项。不得因本计划完成归档整个变更。

## 本次验证记录（2026-10-30）

- Python 3.9.6 下 18 项 unittest 通过：初始正常路径先失败，权限恢复及占位 README 缺陷也各自先复现后修复。
- 独立审查发现 2 项 P2，修复后复核通过；没有未处理的重要问题。
- 6 个合成技能行为场景的结果与局限见 [行为记录](../../../tests/behavior.md)。独立模拟不代替宿主及业务验收。
- Skill quick_validate 与 OpenSpec 严格校验通过；20 个 Markdown 文件、37 个本地链接及锚点检查通过。校验器所需 PyYAML 只安装于本地忽略目录，不是安装器运行依赖。
- zkxw 隔离试点完成预览/安装/重复/恢复/再安装；既有受跟踪文件恢复字节一致，主目录保留原状态。工程配置记录用户已确认的 V2.0 与 Drone 输入，没有核查流水线。
- 原始 Skill 自包含；候选上游仅记录固定来源和入口摘要，尚未证明全套依赖与行为兼容。Cursor 实际会话、正式业务工单、夜间调度与发布留待后续阶段。
