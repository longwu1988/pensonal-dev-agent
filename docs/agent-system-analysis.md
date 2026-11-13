# 个人智能体思路分析与可诊断调整点

本文是对本仓库「个人开发智能体」思路的只读沉淀，对应 2026-11-11 分析结论。**不是**已交付能力说明；成熟度以 [README](../README.md#当前状态) 为准。

后续已确认进入 **P0**：先落[阶段 3 宿主验收剧本](stage3-host-acceptance.md)与 [CLI 硬化候选](cli-hardening-candidates.md)，再按证据改规则或运行时。本文件不替代上述执行材料。

## 一句话结论

这套体系的核心不是「多 Agent 自动干活」，而是：用可安装 Skill + 本地 CLI 状态机，把开发流程压成「分级路由 → 单主流程 → 证据收尾」。当前已可本地安装、合成测试较厚，但两端真实会话与上游组合仍未闭环；日用最痛的是「规则厚、运行时管不住」。

## 1. 在解什么问题

第一版提案针对：上游技能各自完整，安装后重复访谈、重复规格，且缺少工程接入与授权约定。跨工程复用的是方法与边界，不是业务命令或试点技术栈。

| 层 | 职责 |
| --- | --- |
| 本仓 | 选能力、消冲突、分发、验证、升级 |
| 业务工程 | 技术栈、目录、验证命令、工单、授权范围 |
| 上游 | 候选能力正文（不复制、不默认全装） |

内容循环：`真实问题 → 案例 → 通用能力 → 验证 → 提交 → 工程主动升级`。

## 2. 架构心智模型

权威来源：[架构设计](../openspec/changes/development-system-v0-1/design.md)。

1. **角色是职责，不是三个原生 Agent** — 见 [roles.md](../skills/personal-dev/references/roles.md)；执行者自查 ≠ 独立审查。
2. **每阶段一个主流程** — 澄清→Matt；UI→Figma；实现/测/审→Superpowers；规格→OpenSpec；禁止全技能串联。
3. **工程配置承载差异** — `docs/agents/project.json`；通用 Skill 不写死试点路径或分支。
4. **结构按能力逐步建立** — `profiles/core.json` 仍为 `candidate-not-behavior-verified`。

近期补丁（2026-11）：[任务分级](../skills/personal-dev/references/task-levels.md)压 token；[题型剧本](../skills/personal-dev/references/playbooks.md)按问题类型设硬加载上限，L1 实施与 L2 文件切开；Figma 门禁替代「简单也要原型」；Cursor「待你确认」+ 末次工具修「只闻声不见题」。

## 3. 运行时画像

入口：[SKILL.md](../skills/personal-dev/SKILL.md) 与 [Cursor adapter](../adapters/cursor/personal-dev.mdc)。

典型 L1/L2：分级 → 读配置 → 新任务版本检查 → 占用与权限 → 关键澄清（待你确认 / 一分钟默认）→ 按级打开 references → 实现与单测 → 串行合入 → 交付证据与关单读回 → worktree 清理或记保留。

| CLI 能管住的 | 仍靠 Agent 自觉的 |
| --- | --- |
| 安装/恢复、占用 CAS、流程标签、本单权限、delivery 阶段字段、`task-next` | 是否先分级、是否写「待你确认」、是否真跑单测、是否建 PR/关单、停手与末次工具、上游调用 |

关键张力：**流程权威在 Markdown，状态权威在 CLI，二者没有强制闭环**。

## 4. 成熟度对照

| 能力层 | 目标 | 现状 |
| --- | --- | --- |
| development-lifecycle | 工单到交付全链 | 规则+部分 CLI；真实 Bug/功能两端未验 |
| workspace-governance | 规则/密钥/清理 | 文档为主；清理靠 Agent |
| capability-distribution | 安装升级+两端验收 | macOS 安装器可用；仅 Cursor adapter；无稳定 Tag |
| knowledge-retrospective | 夜间报告与提炼 | 几乎未开始 |
| queue / continuous-watch | 队列与定时新单 | 合成实现厚；真实仓与宿主调度未验 |

实质停在阶段 2 + 队列/权限扩展；阶段 3–5 未闭环。

## 5. 可诊断调整点

### P0 — 能不能用

| 点 | 信号 | 先查 | 可调 |
| --- | --- | --- | --- |
| A. 宿主执行落差 | 合成全绿、真会话漏关单/漏清单 | 一条「领单→改→单测→合入→关单」对照 delivery / 远端 closed | 先跑[验收剧本](stage3-host-acceptance.md)；缺证据保持「未验证」 |
| B. 规则厚、CLI 管不住 | 只 push 不关单；只播音不见题 | `queue-finish` / delivery-status /「待你确认」/ 末次工具 | 按[硬化候选](cli-hardening-candidates.md)收门禁；入口摘要缩短 |
| C. Cursor 确认可见性 | 听见音却无题；播音后继续改 | visibility 文件、工具顺序、Queued | 强制复制 visibility；正文先于播音 |

### P1 — 成本与可信度

| 点 | 信号 | 先查 | 可调 |
| --- | --- | --- | --- |
| D. 加载预算 | 咨询也读全 Skill；小修走 OpenSpec/Figma | 题型剧本 + L0/L1/L2；实际打开的 references 是否超出上限 | 强化 adapter；短剧本白名单；后续可考虑 CLI `route` 返回强制 read 列表 |
| E. 一分钟边界 | 沉默当验收/授权 | 题型、发送时间、停止优先 | 超时不授权限；不可计时则必须等待 |
| F. Figma 门禁 | 有参考仍原型 / 无参考直写 | 同端参考依据；免除是否用户明确 | 按 2026-11-11 现行门禁；勿读作废 behavior 节 |
| G. 权限双重门禁 | guard 过了仍失败；deny 被工程 true 盖 | permissions-check；deny 优先 | 「守卫 ≠ 授权」短检查；写入前重读 |

### P2 — 体系闭环

| 点 | 信号 | 可调 |
| --- | --- | --- |
| H. 上游未落地 | providers 有路由、安装器不装上游 | 最小组合+冲突案例，或明确降级路径 |
| I. watch / 复盘 | `active` 无宿主唤醒 | 未验收不宣传无人值守；复盘留阶段 4 |
| J. 升级摩擦 | 旧 updater 拒新文件；无 Tag | 新运行时强制完整 `init`；Tag 放阶段 5 |
| K. Codex 对等 | 仅 Cursor adapter | 补宿主差异并分别验收 |

## 6. 日常诊断清单

1. 本任务级别？有无不该有的占用 / 一分钟 / Figma？
2. 可见回复有无「待你确认」？播音是否末次工具？
3. `task-next` / `delivery-status` / `permissions-status` 与口头宣称是否一致？
4. 关单是否远端读回 `closed`？最终是否含单测 / 合入或 PR / 构建留给用户？
5. 完整协议运行时还是 Skill-only？（后者无原子占用却口头「领取」= 假保障）

分流：停太多 → 级别/Figma/改端误触发；假完成 → 收尾证据与权限；宿主怪 → 播音顺序与 visibility。

## 7. P0 执行顺序

1. 按 [stage3-host-acceptance.md](stage3-host-acceptance.md) 跑最小实机剧本（先 Cursor，可选 Codex）。
2. 按 [cli-hardening-candidates.md](cli-hardening-candidates.md) 硬化已选定的 2–3 个门禁（实现另开变更）。
3. 宿主计量 L0/L1 与 Figma 门禁是否降 token/停顿。
4. 再谈上游组合、watch、复盘、发布。

## 参考

- [README](../README.md)
- [design.md](../openspec/changes/development-system-v0-1/design.md)
- [SKILL.md](../skills/personal-dev/SKILL.md)
- [task-levels.md](../skills/personal-dev/references/task-levels.md)
- [playbooks.md](../skills/personal-dev/references/playbooks.md)
- [behavior.md](../tests/behavior.md)
- [profiles/core.json](../profiles/core.json)
