---
name: personal-dev
description: Use when starting a project, implementing a tracked feature, fixing a bug, receiving acceptance feedback, committing/pushing an existing task, preparing delivery, or starting, stopping, inspecting or resuming an issue queue, or continuously monitoring future issues in a project using the personal development system. Not for concept-only questions or unrelated tasks.
---

# 个人开发任务入口

从工程根目录读取 `AGENTS.md` 和 `docs/agents/project.json`；缺失配置时先列出缺口，只补当前阶段必要事实。遵守宿主与用户指令，本技能不授予外部写操作权限。

用户要求持续监听、定时处理或以后新增工单也自动处理时，先读[持续检查](references/issue-watch.md)；只要求开始、结束、查看或续接工单队列时，先读[工单队列](references/issue-queue.md)并进入对应分支；停止优先于更新检查、澄清等待和交付收尾。

新任务首次启用本技能时先按[版本检查与更新选择](references/updates.md)调用检查入口；同一任务续聊不重复检查或更换规则。检查失败沿用已安装版本，不阻塞业务。

1. 判断任务与已完成阶段，复用工单、用户确认及现有 worktree 的证据。涉及关键未知项时按[澄清与推荐选择](references/planning.md#关键疑问先澄清)处理，对已采用全量默认策略的任务统一提供推荐并等待 180 秒，再定稿相关文档或开发；按下表读取其余分支。
2. 开始实现前明确验收条件、集成分支、影响应用及对应目录规则；修改端不明确时按[实施流程](references/implementation.md)先确认范围，并读取[测试责任](references/testing.md)；默认 Agent 测试，用户明确自测时按用户模式交付。未知环境不视为已验证。
3. 用户确认通过、要求提交/push/合并或从中断续接时，先读[工单收尾检查](references/completion.md)，恢复原任务的关联与未完成步骤；已有授权下完成关单及读回核验，不能只做最后一句 Git 动作。用户明确限定动作或停止时保留剩余待办。
4. 移交时保留“当前阶段、依据、下一动作、验证缺口”。交付前读取交付分支，不能以提交成功代替验收。

| 任务 | 读取 |
| --- | --- |
| 空白工程、大需求、技术栈或架构变化 | [建设与规格](references/planning.md) |
| 拉取工单、理解评论和截图、续接工单或交付前核对补充 | [工单全文、评论与图片](references/issue-context.md) |
| 正式功能、局部 Bug、界面实现 | [实施流程](references/implementation.md) |
| 安装或更新依赖、下载工具链、配置 CI/Docker 构建源 | [依赖下载与镜像](references/dependency-downloads.md) |
| 配置应用运行密钥，或使用服务器、仓库、设计平台等操作账号 | [运行凭据与 Agent 操作凭据](references/credentials.md) |
| 界面实现、布局样式修改，含原型豁免与已有组件复用 | [界面一致性、原型与验收](references/ui-design.md) |
| 切换本机运行版本、集成冒烟、恢复环境或验证失败后修复 | [本机环境验证与集成](references/local-validation.md) |
| 审查、推送、合并、打包、清理 | [交付流程](references/delivery.md) |
| 需要协调、执行或独立审查职责 | [角色边界](references/roles.md) |
| 调用 Matt、Superpowers、OpenSpec 或 Figma | [能力选择](references/providers.md) |

纯咨询直接答复；无行为变化的小文字修正按影响检查，不开启完整工单/设计流程。若安装了职责重叠的技能，先按能力选择检查是否存在实际冲突，不能靠重复运行所有流程解决。

仅安装本 Skill 不会安装插件、创建工程配置或连接 MCP。上游缺失时可进行本技能明确的通用步骤；依赖特定工具的步骤保持待处理，不伪造调用。
