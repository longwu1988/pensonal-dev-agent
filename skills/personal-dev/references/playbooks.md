# 题型剧本与加载上限

在打开流程表或其它 references 之前，先用本条消息判定**题型剧本**，再映射到 [任务级别](task-levels.md)。本文件是日用短路径的权威来源；级别表管上调与全局禁止，剧本管「这次只做什么、最多读什么」。

入口与 Cursor 适配器只保留判定摘要，不复制整表。

## 判定顺序

1. 用户点名队列启停、持续监听、worktree 巡检、版本更新 → 不走下表短剧本，直接进对应引用（见 Skill 分支表）。
2. 否则按下表匹配**第一个**符合的剧本；边界不清时取更重的一个，并简短告知。
3. **只打开该剧本「允许读取」列**；未列出的流程引用本轮不读。需要上调时先换剧本或升到 L2，再扩大读取。
4. 执行中发现跨模块 API/业务规则变化、无可用界面参考须定口径、或验收不清 → 升 `P-feature`（L2）或触发 Figma，不因赶时间留在短剧本。

## 日用剧本

| 剧本 | 典型触发 | 级别 | 步骤（按序，勿加戏） | 允许读取 | 硬禁止 |
| --- | --- | --- | --- | --- | --- |
| **P-ask** 咨询解释 | 解释概念、对比方案、问「是什么/为什么」；不改仓库 | L0 | 直接答复 → 结束 | 无流程引用；必要时只读相关代码/配置 | 版本检查、占用、worktree、Figma、「待你确认」、一分钟、改端问卷、project.json 全量 |
| **P-locate** 只读定位 | 找文件/调用链/根因线索；明确不改或先查清 | L0 | 检索定位 → 给出路径与结论 → 结束（用户再说再改） | 无流程引用；只读代码/配置/日志 | 同 P-ask；不创建工单、不改文件 |
| **P-patch** 单点修补 | 无工单号的文案、配置、局部逻辑；范围已能从对话或打开目录唯一推断 | L1 | 推断范围 → 修改 → 最小验证 → **停在可续接**（未点名不交付） | [implementation-l1](implementation-l1.md)；改代码时 [testing](testing.md)；涉及样式时 [ui-design](ui-design.md) 门禁节 | OpenSpec 全套、新建 worktree、完整 delivery、默认全文评论、无依据的改端问卷；**跳过**新任务版本检查 |
| **P-bug** 带编号小 Bug | 用户给出工单号/链接，且是恢复既有行为的局部缺陷，非新能力 | L1 | 领取 → 读正文与**当前相关**评论 → 修 → 最小验证 → 未点名交付则停 | [issue-claims](issue-claims.md)、[issue-context](issue-context.md)（按 L1 预算）、[implementation-l1](implementation-l1.md)、[testing](testing.md)；写入前 [permissions](permissions.md) | OpenSpec 全套、默认完整交付链、不默认翻完全部历史评论；**跳过**新任务版本检查 |
| **P-ui** 界面微调 | 布局/样式/文案微调，且有同端同类参考或用户已给视觉依据 | L1 | 过 Figma 门禁 → 留下视觉依据 → 改 → 视觉自检 → 未点名交付则停 | [ui-design](ui-design.md)、[implementation-l1](implementation-l1.md)；有编号时加 P-bug 的工单读取 | 门禁未触发时不做原型、不发起原型一分钟；**跳过**新任务版本检查 |
| **P-feature** 正式功能 | 新能力、跨模块、规则/API 变化、空白工程/栈变化、正式工单开发交付、用户要求完整流程 | L2 | 按 Skill 正式链：配置 →（新任务）版本检查 → 占用/规格 → 实施 → 测 → 交付 | 按 [task-levels L2 预算](task-levels.md#按级允许读取) 与 Skill 分支表按需打开 | 仍每阶段一个主流程；不串联全部上游技能 |
| **P-deliver** 仅交付 | 已实现，用户只要提交/push/PR/合并/关单或验收后续接收尾 | L1 或 L2 | 读收尾 → 补齐未完成交付步骤 → 关单读回（已授权时） | [completion](completion.md)、[delivery](delivery.md)、[pull-requests](pull-requests.md)；需要时 [permissions](permissions.md)、[local-validation](local-validation.md) | 不重做实现与规格；不借交付重开澄清访谈 |

有工单号但诉求是**新功能/改规则** → `P-feature`，不是 `P-bug`。  
「顺便解释再改一处」→ `P-patch`（或带号则 `P-bug`），不是 `P-ask`。  
「先帮我看看再决定改不改」→ `P-locate`。

## 加载上限（硬约束）

| 剧本 | 本轮流程类文件上限（不含用户点名的单文件） | 说明 |
| --- | --- | --- |
| P-ask / P-locate | **0** | 不得打开 SKILL 流程表或其它 references |
| P-patch / P-ui | **≤ 3** | 通常为 implementation-l1 +（testing 或 ui-design） |
| P-bug | **≤ 5** | 含领取与工单上下文；不得借机读 delivery/planning 全文 |
| P-deliver | **≤ 4** | 只围绕收尾 |
| P-feature | 按 L2 预算 | 仍禁止一次读完全部 references |

超过上限才能继续时：先上调剧本或级别，再读；并告知用户为何加重。

## 与级别、一分钟、版本检查的关系

- **级别**：剧本选定后即确定默认级别；上调规则仍以 [task-levels](task-levels.md) 为准。
- **一分钟 /「待你确认」**：仅 `P-feature` 及短剧本中**不可推断且会影响范围/验收**的决定；`P-ask`/`P-locate` 禁用；`P-patch`/`P-bug`/`P-ui` 能唯一推断则不问不候。
- **版本检查**：仅 `P-feature`（及用户点名更新、队列/监听启动）在新任务首次按 [updates](updates.md) 检查；短剧本默认沿用已安装版本，不阻塞、不发起更新选择。

## 移交摘要

换人或中断时保留一行：`剧本=…；级别=…；依据=…；下一动作=…；验证缺口=…`。
