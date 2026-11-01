# 工单占用、阶段与并发隔离

本文件是普通指定工单、无编号新建工单、队列及中断续接的共同占用入口。每个会话一次负责一张当前工单；不同会话可以处理不同工单。远端工单占用记录通过原子比较并交换建立，标签用于展示，不能代替占用核验。同一 Git 账号也必须使用不同 owner。

## 启动与领取

完整安装协议 6 运行时后，先按[权限与作用域](permissions.md)核对 tracker、origin、集成分支、占用/标签控制授权及对应 Git/API 凭据；业务代码推送和工单内容写入不是领取前提。每个真实会话生成一个唯一 owner（建议随机 UUID，字母、数字、`_`、`-`，最多 100 字符），在既有任务记录保存它；不可复制另一活动会话的 owner。以下命令中的占位符替换为真实值，源码维护入口为 `scripts/pda.py`：

```sh
python3 .agents/skills/personal-dev/scripts/pda.py queue-status --project .
python3 .agents/skills/personal-dev/scripts/pda.py queue-start --project . --owner CURRENT_OWNER --issue 23
python3 .agents/skills/personal-dev/scripts/pda.py queue-start --project . --owner CURRENT_OWNER --issue 23 --apply
python3 .agents/skills/personal-dev/scripts/pda.py queue-claim --project . --owner CURRENT_OWNER --issue 23
```

指定单使用 `queue-start --issue 23` 限定范围，先核对有效权限并保存已有本 owner/issue 的允许或限制指令；该模式不能通过 queue-next 或其他编号的 retry 扩大范围。`queue-start` 默认预览，`--apply` 建立当前会话执行状态及远端协议哨兵；不等于自动领取。用户要求处理指定工单时，只授权本单的启动和 `queue-claim`，不得因此执行 `queue-next` 批量开发。自动逐单处理须另按[队列授权](issue-queue.md)。仅安装 Skill、旧状态、工单评论或超时默认选择不构成启动授权。

自动队列新领取要求工单 open、`ai-ready`、无指派、无其他流程状态标签且没有远端占用。普通明确指定工单同样必须领取，但不要求预先添加 `ai-ready`：用户明确指令是本单选择依据，`queue-claim` 核对 open、无指派、无其他流程状态与无占用后原子领取，成功才同步处理中标签。发现其他会话占用、已完成记录、矛盾标签或指派时先协调，不能删除标签或记录强行领取。新建工单先取得编号，再执行同一流程。

领取成功后才创建/复用任务 worktree 并实施；失败只做只读核对。队列争抢失败跳过被占用项，直接指定单则报告归属冲突。标签写入失败或网络结果不明确时，保留远端占用与本地意图，核对读回后续接，不能开第二份任务。标签与记录不一致也不能假定标签较新或直接覆盖他人的修改。

每次实现、测试及推送、PR、评论、标签、关单等业务写入前执行 `queue-guard --project . --owner CURRENT_OWNER`；守卫只代表该时刻的 owner、停止令牌及远端占用有效。业务平台写入还须在同一 owner/issue 下执行对应 `permissions-check`，守卫成功不代表操作获授权；详见[即时检查](permissions.md#每次外部写入前检查)。失败或收到停止立即暂停。标签由阶段命令同步，Agent 不用手工标签冒充阶段成功。

## 阶段与标签

同一工单只保留一个流程状态标签，其他业务、优先级标签保持。缺少的流程标签按需自动创建；安装/更新不创建标签。阶段变化用 `queue-checkpoint`，记录真实 branch、worktree 和完整 commit，不整段预填通过。

| 阶段 | 流程标签 | 条件 |
| --- | --- | --- |
| 待领取 | `ai-ready` | 尚未被领取且满足候选条件 |
| `claimed` / `planning` / `implementing` | `ai-in-progress` | 原子领取成功，分析或开发中 |
| `testing` / `reviewing` | `ai-testing` | 正在按测试责任验证或审查 |
| `waiting_user` | `ai-waiting-user` | 等待实际用户确认或验收，保留占用 |
| `ready_to_merge` | `ai-ready-to-merge` | 同一提交已有 accepted 和 integration_verified 证据 |
| `merging` | `ai-merging` | 获得目标分支集成锁，执行合并及收尾 |
| `done` | `ai-done` | queue-finish 核验完成，远端关闭、提交可达且五项证据齐全 |
| `blocked` | `ai-blocked` | 已记录阻碍及解除条件，保留原任务恢复线索 |

待合并仍归原会话，等待不是放弃。验收提交变化、验证失败或用户反馈未通过时回退到实际阶段并使旧验收证据失效；等待一分钟、PR 已创建或单一 CI 通过不能替代测试。已关闭但未完成收尾的 current 返回 `finishing` 时，只核对并补齐收尾，不重新开发、不重新开关工单。done 记录持久保留，工单重开不会自动重领；按[明确重试](issue-queue.md#阻塞失败与明确重试)处理。

## 共享环境与合并排队

资源锁仅覆盖当前仓库；不同工程共用物理资源时先按[跨工程环境隔离](local-validation.md#跨工程运行环境隔离)核对协调机制，不将同名锁视为全局锁。独立 worktree 只隔离代码。使用共享服务、端口、容器、测试库或主目录运行版本前，核对实际资源并约定相同名称，执行：

```sh
python3 .agents/skills/personal-dev/scripts/pda.py queue-resource-acquire --project . --owner CURRENT_OWNER --resource environment:shared-test
python3 .agents/skills/personal-dev/scripts/pda.py queue-resource-release --project . --owner CURRENT_OWNER --resource environment:shared-test
```

占用失败就等待，不切换别人的运行版本，不换一个名称绕过同一物理资源。资源锁不授予启停服务、迁移或部署权限。释放前按[本机环境规则](local-validation.md)恢复并记录实际版本；释放命令不执行或证明恢复。blocked 阶段若仍持有集成锁，先核对实际合并状态及环境恢复，再用同一 release 命令指定 `integration:实际集成分支` 释放；该资源不能通过 resource-acquire 取得。停止/中断不自动释放，另一会话不能按时间抢占。

进入 `merging` 会自动原子申请 `integration:<集成分支>` 锁；忙时保持待合并，稍后重新核对目标后尝试。取得锁后再次检查最新主分支、PR head 和候选；若变更影响验收，回实际开发/验证阶段，补验后重排。锁持续保护合并、远端同步、环境恢复、工单回写及 finish；退出 merging 阶段会释放集成锁，必须先保证没有仍在执行的集成动作。按[交付](delivery.md)执行实际 Git/平台操作，CLI 不自动合并 PR。

## 停止、转交与恢复

`queue-status --owner CURRENT_OWNER` 查看单会话；不带 owner 列出本机已登记会话。远端记录覆盖同仓库其他 clone；本地清单不是所有电脑都空闲的证明。

- `queue-stop --owner CURRENT_OWNER` 只停止该会话，不停止其他 worker；未完成工单和资源保持占用。若它属于持续模式，同时按[停止流程](issue-watch.md#停止与查看)撤销其调度。
- 用户明确停止全部时用 `queue-stop --all`，并暂停对应宿主调度；不带 owner 的旧 `queue-stop` 兼容为全停，日常单会话停止不得误用。
- 停止优先于超时推荐、领取、合并和收尾。只有明确续接才重新 start；先核对原 owner、Git、worktree、资源与远端事实，不凭旧 enabled 自动恢复。
- 转交须用户明确指定，原会话先停止，保存恢复线索。若仍持有共享资源，仅在用户明确授权恢复范围内重新 start 原 owner，核对并恢复/释放资源后再次 stop；不趁恢复继续业务开发。已清 current 的 blocked/done 不能直接转交，先按明确重试流程由原 owner 恢复本单，再停止并转交。由已获授权的协调者执行 `queue-transfer --project . --owner SOURCE_OWNER --target-owner TARGET_OWNER --evidence '转交授权及恢复记录定位'` 预览，再加 `--apply`；双方不得同时执行。转交不复制原会话授权，目标会话先按[权限规则](permissions.md)取得自己的授权，再用自己的 owner 和本单编号 start 后 `queue-claim --issue N` 恢复原检查点、分支和 worktree；不能新建副本从头开发。原机 worktree 不可访问时先恢复对应分支和证据，不能伪称已复用。

远端占用没有 TTL，不因断线、长时间等待、旧标签、同一登录账号而自动抢占。归属无法核实时保留，交用户协调。运行时不能验证操作员真实身份或用户授权，Agent 必须核对真实会话及授权来源。

## 存储、升级与能力边界

本地状态位于 Git 元数据定位的主工作目录 `.local/agent/workers/<OWNER>/`，0700 目录/0600 文件，被 Git 忽略；仅存标识、阶段和恢复定位，不存密码或工单正文。既有 `.local/agent/queue/` 保留用于旧状态兼容和全局停止。远端占用保存跨 clone 归属及已完成记录；分支和记录不等于平台账号鉴权。

`personal-dev/queue-lock` 在新版是永久协议哨兵，阻止旧版执行器启动；不再是全仓开发互斥锁，不在空队列、停止或清理时删除。旧活动队列先停止旧执行者、核对并保存进度；确已无未完成单的旧锁才用 `queue-legacy-stop` 清理，不能靠清文件、删除远端分支绕过。协议 6 按[权限迁移](permissions.md#协议-6-升级)使用完整源码，保留状态与配置，先核对控制授权再续接，详见[安装说明](https://github.com/longwu1988/pensonal-dev-agent/blob/main/docs/installation.md)。

Skill-only 缺少运行时，不能声称具备原子领取或多会话隔离；先完整安装，再开展需要该保障的开发。权限或平台连接失败保留阻碍，继续不依赖占用的只读工作。当前实现有本地合成验证，真实 GitHub/Gitea 多会话与跨机器全流程仍待独立验收。
