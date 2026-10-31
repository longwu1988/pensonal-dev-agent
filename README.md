# pensonal-dev-agent

个人开发体系：从真实工程中提炼可复用的开发流程、Skills、Agent 角色和工具适配，逐步形成可安装、可验证、可升级的能力集合。

## 当前状态

仓库处于最小接入试验阶段：已提供本地安装器、个人任务入口和分层流程。尚未发布稳定版本，真实业务场景及两端会话验收仍待完成。

- 首个试点工程：`zkxw`。
- 第一版目标工具：Codex、Cursor；Claude 暂不纳入实施和验收。两端适配均待验证。
- `scripts/pda.py` 提供预览、安装、只读检查和恢复；使用 Python 3.9+ 标准库，目前验证 macOS，Linux 尚未实测，Windows 不支持。
- 完整安装额外提供按工程检查 main 更新、稍后提醒、跳过版本及固定提交升级；由新任务入口调用，没有后台调度或宿主启动钩子。用法与边界见 [更新说明](docs/installation.md#按工程检查与选择更新)。
- `skills/personal-dev/` 提供任务路由及协调/执行/审查职责。角色是可读职责定义，不是自动启动的宿主原生 Agent。
- `main` 是工程接入与更新检查的入口；当前仍为试验能力，尚无 npm 包或稳定发布 Tag。
- 完整接入使用本地脚本，见 [安装与验证](docs/installation.md)。单独安装 Skill 不会安装依赖或初始化工程；本轮未验证 npx skills 分发。
- zkxw 已单独接入上游技能和 Figma；本安装器仅检查本地事实，不下载安装上游、修改账号或启用夜间调度。

## 第一版方案入口

第一版约定覆盖新工程建设与已有工程日常开发。技术栈由项目整体需求决定，随需求演进受控调整，不固定为试点工程的选择。

| 要处理的事项 | 查阅入口 |
| --- | --- |
| 范围、成熟度与交付顺序 | [变更提案](openspec/changes/development-system-v0-1/proposal.md) |
| 角色分工、上游组合与适配边界 | [架构设计](openspec/changes/development-system-v0-1/design.md) |
| 工单、Figma 验收、worktree、合并与 Drone 打包 | [开发与交付规范](openspec/changes/development-system-v0-1/specs/development-lifecycle/spec.md) |
| 规则分层、目录、密钥与文件清理 | [工程治理规范](openspec/changes/development-system-v0-1/specs/workspace-governance/spec.md) |
| 初始化、依赖、Codex/Cursor 接入与升级 | [分发规范](openspec/changes/development-system-v0-1/specs/capability-distribution/spec.md) |
| 知识沉淀、夜间报告与人工审查 | [复盘规范](openspec/changes/development-system-v0-1/specs/knowledge-retrospective/spec.md) |
| 设计基线任务 | [阶段 1](openspec/changes/development-system-v0-1/tasks.md) |
| 最小接入实现与验证 | [阶段 2](openspec/changes/development-system-v0-1/implementation.md) |

以上是完整体系的目标要求，部分已由最小接入实现；尚未完成全部验收，不归档为已交付的长期规范。

## 能力来源与组合方向

以下是已确定的职责分工，实际组合仍需经过试点验证。候选来源、完整 commit、许可及入口摘要记录在 [core profile](profiles/core.json)；本仓库不复制上游正文、不安装上游依赖。

| 来源 | 拟复用的能力 |
| --- | --- |
| [Matt Pocock Skills](https://github.com/mattpocock/skills) | 需求澄清、领域建模、模块设计、复盘 |
| [Superpowers](https://github.com/obra/superpowers) | 实现、调试、测试、审查、完成验证 |
| [OpenSpec](https://github.com/Fission-AI/OpenSpec) | 需求与设计记录、任务、规范变更和归档 |
| [Figma MCP](https://developers.figma.com/docs/figma-mcp-server/) | 界面原型、设计读取与实现对照 |

本仓库负责选择能力、协调重叠流程和适配工具。业务工程保留自己的业务规则、数据约束、目录结构和验证命令。

## 内容如何积累

真实工程中的问题 → 可复现案例 → 提炼通用能力 → 验证 → 提交 → 发布 → 工程主动升级。

第一轮验收覆盖一个空白工程、试点中的一个 Bug 修复和一个功能变更。当前目录按已实现能力建立：

| 目录 | 职责 |
| --- | --- |
| `skills/` | 可复用任务流程及所需资源 |
| `skills/personal-dev/references/roles.md` | 工具无关的角色职责；随 Skill 一起分发 |
| `scripts/` | 本地安装、配置校验、事务恢复及状态检查 |
| `adapters/` | Cursor 的规则入口；两端共享同一份 Skill |
| `templates/` | 提供给使用方工程的初始化模板 |
| `profiles/` | 固定来源的候选能力组合，行为验证状态显式标记 |
| `tests/` | 安装器测试与技能合成行为验收记录 |

目录名本身不会让工具自动加载角色，也不会自动安装第三方插件。引入分发能力时，应同时提供对应的安装、验证和升级说明。

## 维护入口

- [AGENTS.md](AGENTS.md)：AI 如何维护本仓库，**不是**安装到业务工程的规则模板。
- [CONTRIBUTING.md](CONTRIBUTING.md)：提炼、验证、提交和发布要求。
- [LICENSE](LICENSE)：原创内容采用 MIT 许可；第三方内容须保留其适用许可和署名。
