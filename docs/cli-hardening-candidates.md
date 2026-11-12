# CLI 硬化候选（P0 选定）

依据 [思路分析](agent-system-analysis.md) 的 P0-B，从「规则已写、Agent 仍可绕过」的失败模式中**选定 3 项**优先硬化进本地 CLI。本文是选型与实现草案，**尚未改代码**；实现须另开变更，并配 unittest +（理想情况下）[宿主剧本](stage3-host-acceptance.md) 回归。

不在本轮硬化：一分钟真实计时服务、PR API 客户端、Figma 连接检查、上游自动安装、无人值守清理。

## 选定总表

| ID | 失败模式 | 今日缺口 | 硬化手段（拟） | 优先级 |
| --- | --- | --- | --- | --- |
| **H1** | 确认清单缺失仍记等待/继续干 | `waiting_user` 只校验 evidence 非空；CLI 看不见聊天正文 | checkpoint / delivery-record 强制结构化确认元数据；`task-next` 在缺字段时 `ask` 升为阻塞 | 1 |
| **H2** | 只 push/合入即宣称完成 | `queue-finish` 已查远端 closed，但 Agent 可不调用 finish 却口头完成 | finish 外增加「完成宣称」只读门禁；缺 closed 读回则拒绝 `status=complete` | 2 |
| **H3** | 未分级就深读全流程 | 级别只在 Markdown；无运行时痕迹 | 可选 `task-level` 记录；`task-next` / 队列推进在缺级别时提示且不返回完整交付链 | 3 |

---

## H1 — 确认清单门禁

### 症状

- 听见 `notify-question` / 固定音，聊天无「待你确认」。
- 已 `checkpoint waiting_user` 或 `delivery-record --stage waiting_user`，但 evidence 只有「等用户」而无题面定位。

### 现状

- [completion.md](../skills/personal-dev/references/completion.md) / planning 要求可见清单；CLI **看不到**会话正文（`task-next` 已注明）。
- `waiting_user` 的 evidence 仅要求可打印非空字符串。

### 拟议契约

进入 `waiting_user`（`queue-checkpoint` 或 `delivery-record`）时，`--evidence` **或**新增可选 JSON 旁路字段必须同时满足：

1. 含字面量 `待你确认`（或固定前缀 `confirm-list:`）。
2. 至少一题的推荐标记（如 `推荐:`）。
3. 至少一处未回复处理（`60s` / `一分钟` / `保持等待` 之一）。
4. 可选：`sent_at` ISO 时间（供一分钟策略；缺省则 `task-next` 声明不可默认采用）。

拒绝示例：`等待用户确认`、`请查看聊天`、空推荐。

`task-next` 在 stage=`waiting_user` 且记录缺少上述字段时：

- `ask` 改为明确阻塞文案：「确认清单元数据不完整；先补 delivery/checkpoint evidence，再播音。」
- `can_merge` 保持 false。

### 验证

- unittest：不合规 evidence → `InstallError`；合规通过；旧不合规记录 status 标 `incomplete_confirm`。
- 宿主：剧本 A2 失败样本在升级后无法再写入合法 `waiting_user`（除非补清单摘要）。

### 局限

- 仍可能伪造清单文字；目标是挡住「零清单」而非语义真伪。
- 不替代 Cursor 末次工具顺序（宿主约束，CLI 无法强制）。

---

## H2 — 关单读回 / 完成宣称门禁

### 症状

- 代码已 push、工作区干净，最终回复写「完成」，工单仍 open。
- 跳过 `queue-finish`，或只用历史 `last_verified` 当当前完成。

### 现状

- `queue-finish` / `delivery-check` 已要求五项证据 + 实时远端 closed + 提交可达。
- Agent 可不调用这些命令却口头结案。

### 拟议契约

新增只读命令（名称可定为 `delivery-complete-check` 或扩展 `delivery-status --require-complete`）：

输入：`--project`、`--issue`、可选 `--commit`、可选 `--owner`。

输出字段至少包括：

| 字段 | 含义 |
| --- | --- |
| `complete` | 仅当 finish 同款实时检查全部通过时为 true |
| `missing` | 缺的 delivery 步骤 / closed 读回 / 提交不同步等 |
| `issue_state` | 本次读取的远端 state（失败则 null + error） |
| `last_verified` | 历史核验时间；**不得**单独使 `complete=true` |

Skill / 交付最终回复规则改为：宣称「工单已关闭并完成」前必须跑本命令且 `complete=true`；否则只能写「代码已推送，工单收尾未完成」及 `missing`。

可选加强（第二刀，仍属 H2）：`queue-finish` 成功后写本地 `completion-receipt`；无 receipt 时 `task-next` 对 done/finishing 提示「勿宣称完成」。

### 验证

- unittest：open 工单 → `complete=false`；closed + 证据齐 → true；伪造 last_verified 不足以 true。
- 宿主：剧本 A8/A9 — 不跑 finish 时 Agent 若仍宣称完成记为失败；硬化后入口应引导先跑检查。

### 局限

- 不阻止 Agent 无视命令撒谎；把「可核对的 complete 位」摆进入口，降低诚实失败成本。
- 不核验 PR 内容映射（仍由 Agent + 平台工具，与现网一致）。

---

## H3 — 任务级别入口痕迹

### 症状

- 咨询题加载完整 Skill / 走占用与一分钟。
- 小修误升 L2 或正式单被当成 L0。

### 现状

- 级别权威在 [task-levels.md](../skills/personal-dev/references/task-levels.md)；无运行时记录。
- `task-next` 不感知级别。

### 拟议契约

1. 新增本地记录（Git 忽略，如 `.local/agent/task-level/<owner-or-session>.json`）：
   - `level`: `L0` | `L1` | `L2`
   - `reason`: 短依据（≤200 字）
   - `issue`: 可选编号
   - `set_at`
2. 命令：`task-level --project . --level L1 --reason '…' [--issue N] [--owner …]`（默认预览，`--apply` 写入，风格对齐 permissions grant）。
3. 行为：
   - **L0**：若误调用 `queue-claim` / `delivery-record`，CLI 拒绝并提示先改级别或确认非咨询。
   - **未设置级别**：`task-next` 返回 `missing: ["task_level"]`，`next` 要求先 `task-level`；仍返回占用信息但不设 `can_merge=true`。
   - **L1**：`task-next` 的 `read` 优先短路径 implementation；不默认丢出完整 delivery 链，除非 status 已在收尾阶段。
   - **上调**：允许 L1→L2 覆盖并保留 reason 历史一条。

### 验证

- unittest：L0 + claim → 拒绝；无 level 时 task-next 缺项；L1/L2 写入可读回。
- 宿主：剧本 B0 — 咨询不应出现 level 记录为 L2 且领单；剧本 A0 — 正式单有 L1/L2 记录。

### 局限

- Agent 仍可虚报级别；硬化的是「无级别就深跑交付」与「L0 误领单」。
- Cursor alwaysApply adapter 仍需保留分级摘要，与 CLI 双轨。

---

## 明确不选入本轮的候选项

| 模式 | 原因 |
| --- | --- |
| 一分钟真实倒计时守护进程 | 与「无后台调度」边界冲突；宿主中断后续跑无保证 |
| 强制 PR API | 超出当前「Agent 调平台工具」设计；工作量大 |
| Figma MCP 连接探测进 pda | 属宿主插件；doctor 摘要足够作状态，不作阻塞安装 |
| 语音必须末次工具 | 宿主工具循环问题，CLI 无法观测工具序 |

## 建议实现顺序

1. **H1** — 与确认可见性事故直接相关，改动面限于 evidence 校验 + task-next 文案。
2. **H2** — 复用 finish/check 逻辑做只读 complete 位，改 Skill 最终回复触发条件。
3. **H3** — 新命令与 L0 拒绝路径；需仔细避免打断已在途的旧会话（缺 level 时警告优于硬拒 claim，或仅对「新 claim」生效——实现时在变更设计里定一条）。

实现变更应更新：`scripts/pda/`、对应 unittest、`skills/personal-dev` 入口与 completion/task-levels 引用，并在 [behavior.md](../tests/behavior.md) 记合成场景；**宿主实机仍以 stage3 剧本为准**。
