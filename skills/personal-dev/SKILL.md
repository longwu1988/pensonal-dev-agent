---
name: personal-dev
description: Use when starting a project, designing or prototyping project UI, implementing a tracked feature, fixing a bug, receiving acceptance feedback, committing/pushing an existing task, preparing delivery, or starting, stopping, inspecting or resuming an issue queue, or continuously monitoring future issues, or inspecting/cleaning task worktrees in a project using the personal development system. Not for concept-only questions or unrelated tasks.
---

# 个人开发任务入口

先按[任务级别与加载预算](references/task-levels.md)判定 **L0 / L1 / L2**，再决定读取范围。L0（解释、定位、对比方案且不改仓库）直接答复，不读下方流程表，不做版本检查，不适用一分钟确认。L1 / L2 再继续。

L1 / L2：从工程根目录读取 `AGENTS.md` 和 `docs/agents/project.json`；缺失配置时先列出缺口，只补当前阶段必要事实。遵守宿主与用户指令，本技能不授予外部写操作权限。工单启动/恢复、权限限制变化及平台写入前，必须读取[权限与作用域](references/permissions.md)，区分控制操作与业务写入，先记录当前限制再执行。

用户要求持续监听、定时处理或以后新增工单也自动处理时，先读[持续检查](references/issue-watch.md)；只要求开始、结束、查看或续接工单队列时，先读[工单队列](references/issue-queue.md)并进入对应分支；停止优先于更新检查、澄清等待和交付收尾。

新任务首次进入 L1 / L2 时先按[版本检查与更新选择](references/updates.md)调用检查入口；同一任务续聊不重复检查或更换规则。检查失败沿用已安装版本，不阻塞业务。L0 不做版本检查。

1. 判断任务级别与已完成阶段，复用工单、用户确认及现有 worktree 的证据。L1 / L2 涉及关键未知项时按[澄清与推荐选择](references/planning.md#关键疑问先澄清)处理，默认提供推荐并真实等待 60 秒，满足前置条件后采用推荐继续；无需单独启用，明确关闭、必须等回复或暂停时遵循该规则的等待分支。按下表只打开当前级别允许的分支。
2. **L1**：按[实施流程](references/implementation.md#l1-轻量路径)短路径执行；有工单编号则领取后改；不默认 OpenSpec 全套或完整交付链。**L2** 正式工单进行中先运行 `python3 .agents/skills/personal-dev/scripts/pda.py task-next --project . --owner CURRENT_OWNER --issue N`。它只读，不领取、不测试、不合入。只打开返回的 `read`；`can_merge` 为 false 时不合入。返回的 `ask` 要求决定时，先写「待你确认」。源码仓库里的入口是 `python3 scripts/pda.py`。没有当前工单时，仍先按[工单占用与隔离](references/issue-claims.md)取得当前会话占用；其他会话占用或已完成时不重复开发。开始实现前明确验收条件、集成分支、影响应用及对应目录规则；修改端不明确时按[实施流程](references/implementation.md)先确认范围，并读取[测试责任](references/testing.md)。默认在 worktree 只运行受影响代码的单元测试，通过后按本机验证规则串行合入集成分支；构建和整体运行验收由用户在合入后进行。用户明确自测时，单元测试也改由用户确认后再合入。未跑过的测试不视为已通过。
3. 用户确认通过、要求提交/push/合并或从中断续接时，先读[工单收尾检查](references/completion.md)，恢复原任务的关联与未完成步骤；已有授权下完成关单及读回核验，不能只做最后一句 Git 动作。用户明确限定动作或停止时保留剩余待办。L1 在用户未要求交付时，实现与最小验证后停在可续接状态。
4. 移交时保留“当前级别、当前阶段、依据、下一动作、验证缺口”。交付前读取交付分支，不能以提交成功代替验收。

| 任务 | 级别 | 读取 |
| --- | --- | --- |
| 判定或上调任务级别 | L0–L2 | [任务级别与加载预算](references/task-levels.md) |
| 工单领取、并行会话、流程标签、转交、共享环境或合并排队 | L1 有编号时；L2 正式单 | [工单占用与隔离](references/issue-claims.md) |
| 发送确认问题、请求用户操作、补发缺推荐或缺超时说明的旧题 | L1 / L2 | 先按[问题展示](references/planning.md#问题展示)与 [Cursor / 工具先于正文的宿主](references/planning.md#cursor--工具先于正文的宿主)在当前回复写出「待你确认」，完成[发问前检查](references/planning.md#发问前检查)后，再按[本地确认语音](references/question-notification.md)提醒；Cursor 下 `notify-question` 须为本轮最后一次工具，且发问后停手 |
| 关闭/恢复声音提醒 | L1 / L2 | [本地确认语音](references/question-notification.md) |
| 空白工程、大需求、技术栈或架构变化 | L2 | [建设与规格](references/planning.md) |
| 拉取工单、理解评论和截图、续接工单或交付前核对补充 | L1 按预算；L2 全文 | [工单全文、评论与图片](references/issue-context.md) |
| 轻量单点修复或小改 | L1 | [实施流程 · L1 轻量路径](references/implementation.md#l1-轻量路径) |
| 正式功能、局部 Bug、界面实现 | L2；界面 L1 亦读 UI 门禁 | [实施流程](references/implementation.md) |
| 安装或更新依赖、下载工具链、配置 CI/Docker 构建源 | L1 / L2 需要时 | [依赖下载与镜像](references/dependency-downloads.md) |
| 配置应用运行密钥，或使用服务器、仓库、设计平台等操作账号 | L1 / L2 需要时 | [运行凭据与 Agent 操作凭据](references/credentials.md) |
| 界面设计或原型、界面实现、布局样式修改 | L1 / L2 涉及界面 | 在调用设计/生成工具前读取[界面一致性、原型与验收](references/ui-design.md)；先过 Figma 门禁，跳过原型仍需核对视觉依据 |
| 单元测试后合入集成分支、避免多个 worktree 同时合入，或验证失败后修复 | L2；L1 需合入时 | [本机环境验证与集成](references/local-validation.md) |
| 创建/复用隔离目录、同名工程或 worktree 命名冲突 | L2；L1 需新建隔离时 | [Worktree 路径与命名](references/worktree-layout.md) |
| 交付后回收或巡检遗留 worktree | 用户点名或 L2 交付后 | [Worktree 生命周期与清理](references/worktree-lifecycle.md) |
| 选择合并方式、创建/续接 PR、检查审查意见或合并状态 | L2；L1 用户要求交付时 | [PR 合并方式与证据](references/pull-requests.md) |
| 审查、推送、合并、打包、清理 | L2；L1 用户要求交付时 | [交付流程](references/delivery.md) |
| 需要协调、执行或独立审查职责 | L1 / L2 | [角色边界](references/roles.md) |
| 调用 Matt、Superpowers、OpenSpec 或 Figma | L2 为主；L1 按需 | [能力选择](references/providers.md) |

L0 与无行为变化的小文字修正不开启完整工单/设计流程；L1 按短路径，发现规则或 API 变化时上调 L2。若安装了职责重叠的技能，先按能力选择检查是否存在实际冲突，不能靠重复运行所有流程解决。

仅安装本 Skill 不会安装插件、创建工程配置或连接 MCP。上游缺失时可进行本技能明确的通用步骤；依赖特定工具的步骤保持待处理，不伪造调用。
