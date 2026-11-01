# 工程权限与单工单授权

本文件是权限能力、授权范围与判定顺序的唯一规则来源。启动/恢复工单、用户缩小权限、平台写入或权限报错时必须先读。工程配置和本地记录表达用户授权，不授予平台账号权限，也不覆盖宿主限制。

## 能力与边界

`docs/agents/project.json` 的 `permissions` 记录工程级长期授权；只有用户明确授予该工程长期权限时才修改，并保存可追溯依据。所有能力初始为 false；旧工程缺少新字段时只在内存补 false，不改原文件，不从旧字段推导新授权。

| 能力 | 授权的动作 |
| --- | --- |
| `manage_claims` | 专用远端控制分支、协议哨兵、工单占用及共享资源记录的维护 |
| `update_issue_labels` | 工单流程标签的创建与同步 |
| `push_task_branch` | 业务代码任务分支推送，不含控制分支 |
| `create_pr` | 创建或更新任务 PR |
| `merge` | 合并任务至已指定集成分支，包括直接合并方式的集成分支推送 |
| `write_issue` | 工单内容及评论写入，不含标签或关闭 |
| `close_issue` | 关闭当前工单 |
| `push_tag` / `deploy` | 分别为 Tag 推送和部署；仍须符合工程约束 |

只有占用与标签权限也能启动限定单、领取和推进允许的阶段；不需要开放业务代码推送或工单评论。平台 Git/API 凭据仍须具备对应能力。`manage_claims` 可能通过远端控制分支触发既有分支 CI，不因此产生业务推送或部署授权。

## 本会话本工单的授权

一次性指令写入主工作目录 Git 忽略的 `.local/agent/permissions/<owner>.json`，不修改 `project.json`。记录绑定实际仓库、目标集成分支、真实会话 owner、工单编号和用户证据定位；不同 worktree 共用主目录状态，另一 owner、另一工单、换仓库或换目标分支均不能借用。证据只存定位，不存凭据或聊天全文。owner 不是身份凭据，不得复制他人的 owner 冒用授权。

判定顺序：宿主/当前用户限制 → 本作用域 deny 或撤销 → 本作用域 allow → 工程级授权 → 默认拒绝。deny 优先于工程 true；撤销后保留拒绝记录，不删除记录后回落工程 true。遇到新的限制，先按已有用户指令落盘 deny/撤销，再尝试任何依赖动作。工单内容、自动收尾惯例、工具报错、安装、无人答复都不能扩大授权。

已存在明确用户授权时直接记录并执行，不重复询问。确需补授权时只问缺少的具体动作、工单/会话和期限范围，说明是哪项操作被阻挡；不能要求笼统“临时开启 push_task_branch 和 write_issue，完成后恢复”。权限不足仍可继续已授权且独立的本地工作。

例如用户明确仅允许当前会话处理 #6 的占用和标签，并禁止业务 push、PR、合并、评论和关单。替换 CURRENT_OWNER 为真实会话标识，证据定位为当前用户原始授权所在消息/记录；示例本身不构成授权：

```sh
python3 .agents/skills/personal-dev/scripts/pda.py permissions-status --project . --owner CURRENT_OWNER
python3 .agents/skills/personal-dev/scripts/pda.py permissions-grant --project . --owner CURRENT_OWNER --issue 6 --allow 'manage_claims,update_issue_labels' --deny 'push_task_branch,create_pr,merge,close_issue,write_issue' --evidence '当前用户授权定位'
python3 .agents/skills/personal-dev/scripts/pda.py permissions-grant --project . --owner CURRENT_OWNER --issue 6 --allow 'manage_claims,update_issue_labels' --deny 'push_task_branch,create_pr,merge,close_issue,write_issue' --evidence '当前用户授权定位' --apply
python3 .agents/skills/personal-dev/scripts/pda.py permissions-check --project . --owner CURRENT_OWNER --issue 6 --capability manage_claims,update_issue_labels
python3 .agents/skills/personal-dev/scripts/pda.py queue-start --project . --owner CURRENT_OWNER --issue 6 --apply
python3 .agents/skills/personal-dev/scripts/pda.py queue-claim --project . --owner CURRENT_OWNER --issue 6
```

status 只要求 `--owner`，返回该 owner 的授权记录及工程权限，不接受 `--issue`；grant/revoke/check 均要求 `--owner --issue`。grant/revoke 默认只预览，加 `--apply` 才写本地记录；status/check 只读取。撤销本作用域时使用 `permissions-revoke --project . --owner CURRENT_OWNER --issue 6 --evidence '用户撤销定位'` 预览，再加 `--apply`。撤销阻止后续动作，保留占用、worktree 与进度，不自动释放资源或关闭工单。停止执行另按队列/持续模式停止流程，不能用重新 start 绕过撤销。

限定单 start 只接受本单：`queue-next` 不能扩大为批量领取，`queue-retry --issue N` 不能越过本单范围。明确转交只迁移占用与进度，不复制授权；目标 owner 先取得自己的合法授权。持续 watch 不能消费单工单 grant：必须拥有工程级 `manage_claims` 和 `update_issue_labels`，并由用户显式开启持续模式；工程权限为 true 也不会自行启动监听。

## 每次外部写入前检查

CLI 在控制状态与标签命令中检查对应控制权限；业务代码 push、PR、合并、评论及关单仍由 Agent 使用既有工具执行。Agent 在这些动作前保留 `queue-guard`，并对当前 owner/issue 执行对应 `permissions-check --capability CAPABILITY`（可逗号列出多项）。分别在推送前查 `push_task_branch`、PR 写入前查 `create_pr`、合并前查 `merge`、工单内容/评论前查 `write_issue`、关闭前查 `close_issue`；禁止用一次批量检查长期替代后续动作的即时核对。

检查失败保留待办，不借用其他 owner、不修改工程开关、不改用直接合并绕过。`permissions-check` 仅证明检查时刻本地授权有效，不会执行外部操作、证明用户身份或绕过平台保护；动作前仍须核对最新指令、停止状态、真实账号及目标。

## 协议 6 升级

旧协议 1–5 需使用完整协议 6 源码预览并执行安装迁移；不能只替换 Skill 文档。保留工程配置、原 owner、占用、队列与交付进度，先停止旧执行者及调度；升级不自动开启控制权限或持续任务。旧工程即使 `push_task_branch`、`write_issue` 为 true，新控制权限和 `close_issue` 仍默认 false。依据已确认的用户授权补充本单记录或工程长期权限，再核对控制授权后明确续接；不能让旧队列绕过新检查。迁移操作见[安装说明](https://github.com/longwu1988/pensonal-dev-agent/blob/main/docs/installation.md)。
