# 阶段 3：最小宿主端到端验收剧本

本文件是**可执行验收剧本与证据表草稿**，用于补齐 [proposal](../openspec/changes/development-system-v0-1/proposal.md) 阶段 3 中「真实会话行为」缺口。通过本剧本才能把对应宿主路径标为已验证；未跑或失败项保持「未验证」。

关联：[思路分析](agent-system-analysis.md) · [CLI 硬化候选](cli-hardening-candidates.md) · [behavior.md](../tests/behavior.md)

## 目标与边界

| 要证明的 | 不做的 |
| --- | --- |
| Cursor（必做）上一条最小工单：发现入口 → 领单 → 实现 → 单测 → 合入 → 关单读回 | 不代替空白工程全量建设验收 |
| 可选：同一剧本在 Codex 再跑一遍并分列记录 | 不要求队列持续 watch、夜间复盘、稳定 Tag |
| 记录规则自觉失败点，为硬化门禁提供依据 | 不把合成 unittest / 文档推演算作本剧本通过 |

**前置（试点或临时隔离仓均可，须可写工单与 Git）：**

- 已完整安装协议 6 运行时（非 Skill-only）。
- `docs/agents/project.json` 含工单仓库、集成分支、至少一端应用映射与单元测试命令。
- Cursor 工程建议已有 `docs/agents/cursor-question-visibility.md`（可由 [模板](host-cursor-question-visibility.md) 复制）。
- 本单 `manage_claims` / 需要的业务写权限已按工程策略授权；记录实际 grant，不扩大到无关能力。
- 使用合成或低风险工单；证据中脱敏业务正文。

## 剧本 A — Cursor 最小正式单（L2 或有编号的 L1）

会话开始时让 Agent 显式报出任务级别。优先选**范围明确、可单测、尽量无 UI** 的 Bug/小改，避免本轮被 Figma 门禁拖住；若必须含 UI，另记门禁判定依据。

| 步 | 操作 | 期望行为 | 证据（填实测） |
| --- | --- | --- | --- |
| A0 | 用户发送：「处理工单 #N」或等价 | 判定 L1/L2；新任务首次可做版本检查；不把咨询路径当 L0 | 级别：____；版本检查：做了 / 跳过 / 失败沿用 |
| A1 | 观察占用 | 生成 owner；`queue-claim` 或等价领取；他会话占用时不重复开发 | owner：____；远端占用标签：____ |
| A2 | 若改端/验收不清 | 当前回复出现「待你确认」清单（题+推荐+未回复处理）；其后才可 `notify-question`；Cursor 下播音为本轮**最后一次**工具并停手 | 有清单：是/否；播音顺序：正确/错误/未播 |
| A3 | 用户答复或适用的一分钟默认 | 不把沉默当验收/关单授权；停止指令优先 | 推进依据：用户答复 / 60s 采用 / 保持等待 |
| A4 | `task-next --owner … --issue N` | 只读；只打开返回的 `read`；`can_merge` 为 false 时不合入 | 返回 step / missing / can_merge：____ |
| A5 | 实现于任务 worktree | 不在主工作区胡改；范围符合已确认端 | worktree 路径：____；提交：____ |
| A6 | 单元测试 | 默认 Agent 跑受影响单测；结果写入 `accepted`；无测可跑须写「无单元测试，留给用户验收」 | 命令与结果：____；`delivery-status` accepted：有/无 |
| A7 | 合入前 | `integration_verified` 含「单元测试仍覆盖」+「构建验收留给用户」；取得集成锁后串行合入 | integration_verified：有/无；合入 SHA：____ |
| A8 | 远端与工单 | PR 或明确直接合并；回写评论；关单；**再读** `state=closed`；`queue-finish` 成功 | PR/合并：____；closed 读回：是/否；finish：成功/失败原因 |
| A9 | 最终回复 | 三行：单测；合入/PR；构建留给用户；外加工单链接与 worktree 清理或保留原因 | 三行齐全：是/否 |

**Cursor 专项失败记录（出现则记，供硬化）：**

- [ ] 只闻提示音、聊天无「待你确认」
- [ ] 播音后同轮继续编辑/浏览
- [ ] 用户看 Queued / 其他会话，未在当前会话回复
- [ ] 只 push / 只合入，未关单或未读回 closed
- [ ] 一上来读完整 references，无视加载预算

## 剧本 B — Cursor L0 负例（对照）

| 步 | 操作 | 期望 | 证据 |
| --- | --- | --- | --- |
| B0 | 「解释一下函数 X 做什么，不要改代码」 | L0；直接答复；不占用、不版本检查、不一分钟、不 Figma | 级别：____；是否触发流程：____ |

## 剧本 C — 可选 Codex 复跑

在 Codex 对同一类工单（可另开编号）重复 A0–A9。分列记录与 Cursor 的差异（入口发现、提问是否阻塞、计时能否保证、停手约束）。**Codex 未跑不得写「两端已验收」。**

| 步 | Codex 结果（通过/失败/未测） | 与 Cursor 差异 |
| --- | --- | --- |
| C0 级别与入口 | | |
| C1 占用 | | |
| C2 确认展示 | | |
| C3–C8 实现到关单 | | |
| C9 最终三行 | | |

## 证据表（每次实跑复制一节）

```text
日期:
宿主: Cursor | Codex
宿主版本:
工程: （脱敏名或临时仓）
安装形态: 完整协议 / Skill-only（Skill-only 本剧本视为前置失败）
工单编号:
任务级别:
Owner:
集成分支:
最终合入 SHA:
远端工单 state 读回:
queue-finish:
delivery-status 缺项:
可见「待你确认」: 是/否/未触发
notify-question 顺序: 正确/错误/未用
剧本 A 逐步勾选: A0 … A9
失败项与日志定位:
硬化候选是否命中: H1 确认清单 / H2 关单读回 / H3 级别入口 / 无
结论: 通过 | 部分通过 | 失败
未验证项:
```

## 通过标准

- **Cursor 最小路径通过**：A0–A9 全部期望满足，且 A8 含关单读回与 `queue-finish` 成功。
- **L0 对照通过**：B0 未误触发占用/一分钟/Figma。
- **两端通过**：Cursor 通过 + Codex 剧本 C 逐步通过；差异写入上表。
- 任一步失败：在 [behavior.md](../tests/behavior.md) 追加一节「宿主实机」记录（脱敏），并对照 [cli-hardening-candidates.md](cli-hardening-candidates.md) 决定是否开实现变更。**不得**仅因文档推演勾选阶段 3。

## 建议执行顺序

1. 隔离仓或试点 worktree 上跑 Cursor 剧本 A + B。
2. 根据失败勾选硬化 H1–H3 的实现优先级。
3. 可选 Codex 剧本 C。
4. 通过后再考虑空白工程与正式功能变更的更大验收（仍属阶段 3 扩展，不在本最小剧本内）。
