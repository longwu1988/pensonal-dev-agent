# pensonal-dev-agent

个人开发体系：从真实工程中提炼可复用的开发流程、Skills、Agent 角色和工具适配，逐步形成可安装、可验证、可升级的能力集合。

## 当前状态

仓库处于设计基线阶段：已整理开发体系的第一版需求、架构和分阶段交付条件；运行能力尚未实现。

- 首个试点工程：`zkxw`。
- 第一版目标工具：Codex、Cursor；Claude 暂不纳入实施和验收。两端适配均待验证。
- 尚未发布可安装的 Skill、Agent 配置、初始化工具或版本。
- 目前不能通过 `npx skills add longwu1988/pensonal-dev-agent` 安装本仓库的开发体系。
- zkxw 已单独接入上游技能和 Figma；这不代表本仓库已提供这些依赖的安装能力。

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
| 本次文档落地工作与后续交付边界 | [实施任务](openspec/changes/development-system-v0-1/tasks.md) |

以上是待实现能力的目标要求，当前保存在 OpenSpec 变更目录；尚未归档为已经交付的长期规范。

## 能力来源与组合方向

以下是已确定的职责分工，实际组合仍需经过试点验证；本仓库尚未引入或安装这些上游依赖。

| 来源 | 拟复用的能力 |
| --- | --- |
| [Matt Pocock Skills](https://github.com/mattpocock/skills) | 需求澄清、领域建模、模块设计、复盘 |
| [Superpowers](https://github.com/obra/superpowers) | 实现、调试、测试、审查、完成验证 |
| [OpenSpec](https://github.com/Fission-AI/OpenSpec) | 需求与设计记录、任务、规范变更和归档 |
| [Figma MCP](https://developers.figma.com/docs/figma-mcp-server/) | 界面原型、设计读取与实现对照 |

本仓库负责选择能力、协调重叠流程和适配工具。业务工程保留自己的业务规则、数据约束、目录结构和验证命令。

## 内容如何积累

真实工程中的问题 → 可复现案例 → 提炼通用能力 → 验证 → 提交 → 发布 → 工程主动升级。

第一轮验收覆盖一个空白工程、试点中的一个 Bug 修复和一个功能变更。能力成熟后按需建立以下目录；当前不创建占位内容：

| 目录 | 职责 |
| --- | --- |
| `skills/` | 可复用任务流程及所需资源 |
| `agents/` | 工具无关的角色职责、输入输出和工作边界 |
| `adapters/` | 各工具的配置生成或转换逻辑 |
| `templates/` | 提供给使用方工程的初始化模板 |
| `profiles/` | 经过验证的能力组合与技术栈配置 |

目录名本身不会让工具自动加载角色，也不会自动安装第三方插件。引入分发能力时，应同时提供对应的安装、验证和升级说明。

## 维护入口

- [AGENTS.md](AGENTS.md)：AI 如何维护本仓库，**不是**安装到业务工程的规则模板。
- [CONTRIBUTING.md](CONTRIBUTING.md)：提炼、验证、提交和发布要求。
- [LICENSE](LICENSE)：原创内容采用 MIT 许可；第三方内容须保留其适用许可和署名。
