# 第一版设计基线 Implementation Plan

> **For agentic workers:** 执行本计划时使用 `executing-plans` 按任务逐项完成；文档写作遵循 `writing-for-agents`。用户已要求在当前会话继续，无需再次询问执行模式。

**Goal:** 将已确认的个人开发体系决策整理为分层、可审查的设计基线，保留真实的能力成熟度。

**Architecture:** README 提供入口，OpenSpec 变更保存提案、架构和四个专题规范。根 AGENTS 仅增加条件索引；本任务不生成运行时能力。

**Tech Stack:** Markdown、OpenSpec spec-driven 配置和本地 Git；文档检查使用已有 Python 3 与可用的 OpenSpec CLI。

## Scope

本计划只实现 [阶段 1](proposal.md#delivery-milestones)。本文件勾选完毕不代表阶段 2–5、行为验收或整个 OpenSpec 变更完成，不得据此归档整个变更。

## Task 1: 分层保存已确认的决策

**Files:** `proposal.md`、`design.md`、`specs/development-lifecycle/spec.md`、`specs/workspace-governance/spec.md`、`specs/capability-distribution/spec.md`、`specs/knowledge-retrospective/spec.md`（均相对于本变更目录）。

- [x] 写入目标工具、角色和上游分工，并区分设计要求与已实现状态。
- [x] 为需求分级、Figma 验收例外、worktree/分支、合并授权、回归和 Drone Tag 打包编写场景。
- [x] 写入目录、密钥和清理要求；保留试点稳定技术栈与已完成 Drone 配置的边界。
- [x] 写入分发、升级和各工具独立验收要求。
- [x] 写入夜间报告、运行条件、失败来源的进度保护和人工审核规则。

**Completion:** 四个专题包含可检查的 Requirement/Scenario；同一规则只在对应专题定义，其他材料引用。

## Task 2: 同步维护入口与成熟度

**Files:** 仓库根 `README.md`、`AGENTS.md`、`CONTRIBUTING.md`、`openspec/config.yaml`。

- [x] README 说明处于设计基线阶段，尚不可安装，提供专题与里程碑入口。
- [x] 将第一版工具范围统一为 Codex、Cursor，说明 Claude 暂缓。
- [x] AGENTS 添加按范围查阅设计的指针，CONTRIBUTING 关联验收与归档边界。
- [x] OpenSpec context 仅保存跨工程定位、文档归属和维护入口。

**Completion:** 文档不会将试点安装状态误写为个人仓库可分发能力，根规则保持简短。

## Task 3: 验证与交付

**Files:** 上述全部修改文件及本 `tasks.md`。

- [x] 使用 `git diff --check` 检查空白错误；预期无输出、退出码 0。
- [x] 检查全部 Markdown 相对文件链接及锚点；预期目标均存在且锚点可解析。
- [x] 检查新增内容无真实凭据、个人绝对路径、业务数据或假定已完成的能力声明。
- [x] 核对用户决策覆盖：Q1–Q19 及技术栈、Figma、V2.0/分支与 Drone 的后续修正。
- [x] 若已有 OpenSpec CLI，运行 `openspec validate development-system-v0-1 --strict`；记录实际结果，工具不可用则报告未执行，不为纯文档任务隐式安装依赖。
- [x] 完成独立文档审查，修正相互矛盾的范围、状态与授权描述。
- [x] 在任务分支提交；按本次授权交付可审查差异，主分支合并和发布分别处理。

**Completion:** 报告实际检查、未执行项与设计/运行能力边界，不报告不存在的单元测试或构建结果。

## 后续里程碑入口

阶段 2 的实施计划应具体定义配置格式、管理文件清单、依赖来源与适配方法，再逐任务实现和验证。阶段 3 需要真实 Bug/功能工单及独立空白工程；阶段 4 在复盘手动试跑通过后创建调度。各阶段完成条件见 [提案](proposal.md#delivery-milestones)，不得将本次文档检查替代这些验收。

## 本次验证记录

- 2026-10-30：OpenSpec 严格校验通过。
- 10 个 Markdown 文件中的 22 个本地链接（含锚点）检查通过；根 AGENTS.md 共 27 行。
- 暂存差异空白检查及个人路径、常见凭据标识定向扫描通过。
- 独立文档审查未发现阻塞或重要问题。
- 未执行运行时、安装器、跨工具行为或夜间调度验证：这些能力尚未实现。
