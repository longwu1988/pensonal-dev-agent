# 能力选择与适配边界

本 Skill 与流程正文是原创适配层，不复制上游技能正文。工程安装器提供的 `docs/agents/personal-dev.dependencies.json` 固定候选来源及入口摘要；仅使用 npx skills 单独安装本技能时，这份依赖记录和工程配置需要另外接入。

| 阶段 | 候选能力 | 使用条件 |
| --- | --- | --- |
| 未完成的需求/领域澄清 | Matt Pocock grilling | 只处理尚未确认决策；已有阶段证据直接移交 |
| Bug 根因定位 | Superpowers systematic-debugging | 核对实际正文与依赖，使用一个调试主流程 |
| 实现测试循环 | Superpowers test-driven-development | 按任务范围执行；不另叠加 Matt tdd |
| 最终结果核验 | Superpowers verification-before-completion | 以实际命令证据判断，不代替独立审查 |
| 规格记录 | OpenSpec CLI/宿主入口 | 读取工程 config，按工程指定产物归属保存 |
| 复杂无参考 UI | Figma MCP | 实际授权与连接可用，按宿主必需技能操作 |

读取实际候选技能及它引用的依赖后才决定调用。本版 doctor 的入口摘要匹配只说明一个文件相同，不能证明完整依赖已固定或行为兼容；候选组合仍待场景验收。

不自动串联 upstream brainstorming、writing-plans、implement 等完整主流程。已确认的设计使用本体系的阶段移交与 OpenSpec 任务；需要上游完整主流程且其硬性指令要求重复访谈或另一产物目录时，明确报告冲突，保留现场，先完成适配再调用，不能声称一句优先级规则已解决冲突。宿主已强制加载的指令仍须遵守。

CLI、插件、MCP 的存在、授权、连接、任务行为分别判断。缺少能力只阻塞依赖它的步骤；本地安装器不自动下载安装上游或配置账号。Figma 服务按宿主插件版本与实际调用记录验证，不把滚动服务写成固定 Git 依赖。
