# 工单收尾记录与完成检查

普通单工单与队列共同遵循本规则。所有新版工单均先按[工单占用](issue-claims.md)领取，续接时核对真实 owner，不能仅凭编号补写其他会话的收尾。用户确认测试通过、要求提交/push/合并，或从中断继续时，先恢复当前任务的工单与未完成阶段，再执行[交付流程](delivery.md)。不能把一句“push”当作忘掉原任务的理由；已有自动收尾授权继续适用。用户明确“只推送、不要关单”或缩小范围时，先按[权限规则](permissions.md)记录本 owner/issue 的 deny，使其优先于工程 true；等待、失败或停止时按新指令保留待办，不越权收尾，不恢复已停止的队列。

## 关联与进度

从对话、工单、现有任务记录核对仓库、工单编号、任务分支/worktree、测试责任、验收提交、集成分支及授权；按[PR 合并方式](pull-requests.md)恢复已选方式和已有 PR。以当前工程配置和实际 origin 为准；多个候选或无法确认关联时先澄清，不能猜编号、批量关闭旧单或把纯 Git 操作强行关联到工单。用户明确只做 Git 操作且没有关联工单时，报告工单收尾不适用。

有待验收提交后，运行时可用时执行以下入口；不依赖启动队列。源码维护时入口为 `scripts/pda.py`。编号、完整 SHA 和证据均替换为本任务实际值：

```sh
python3 .agents/skills/personal-dev/scripts/pda.py delivery-status --project .
python3 .agents/skills/personal-dev/scripts/pda.py delivery-status --project . --issue 23
python3 .agents/skills/personal-dev/scripts/pda.py delivery-record --project . --issue 23 --commit FULL_40_CHARACTER_SHA --stage waiting_user --evidence '待用户测试；实际任务分支、worktree、入口与验收记录定位'
```

上面三条不是必须顺序执行的初始化脚本；只有实际进入待测/失败阶段才记录 `waiting_user`，续接已验收任务时不要重置记录。

`delivery-status` 不联网、不创建记录；返回 `last_verified` 仅是历史核验时间，**不是当前完成状态**。各 worktree 经 Git 定位共用主工作目录 `.local/agent/delivery/`。记录被 Git 忽略、文件权限 0600，仅存版本和证据定位，不写密码、Token、完整工单正文或图片。安装/更新不清除记录，换电脑需从可信工单和远端重建；本功能不是多电脑任务锁。

按照实际阶段调用 `delivery-record`，不能整段预填“通过”：

| `--stage` | `--evidence` 必须能定位的事实 |
| --- | --- |
| `waiting_user` | 待测或反馈失败，写明任务分支/worktree、提交、运行入口和待办；清除本轮通过记录 |
| `accepted` | 测试责任、对应提交、Agent 真实测试或用户明确通过的记录，以及适用的审查结果 |
| `integration_verified` | 最终合并内容对应的集成环境验证；纯文档可记录不适用及依据 |
| `remote_synced` | 实际仓库、集成分支与远端最终提交；PR 模式附 PR 链接、base/head、实时 merged 状态及内容映射；直接合并附明确选择依据 |
| `environment_restored` | 实际运行版本恢复/沿用相同已验收环境的依据；不适用须有理由 |
| `issue_updated` | 已写入工单的验收/交付评论链接或 ID，包含测试责任、提交及对应 PR（直接合并时说明选择依据） |

后五项使用相同命令形态，将 `--stage` 和 `--evidence` 换为对应真实结果。证据不确定时保留缺项，不能填 `N/A` 绕过。更新较早阶段且证据发生变化会清除下游记录；相同阶段/证据重试不重复推进。提交改变会归档旧记录并清空本轮证据，包括 squash/rebase 或合并 SHA 改变；先核对内容与环境等价性，再逐项记录可复用依据，不能自动继承旧验收。后续失败即使提交未变，也先记录 `waiting_user` 或更新相关阶段使旧完成证据失效，说明实际阻碍。

未安装运行时的 Skill-only 工程，使用已有工单/任务记录保存相同清单，按下节通过已授权工具逐项检查并明确“人工核对”；提示完整安装，不虚称脚本已执行。认证或 Git 检查失败也不能通过手写“已完成”绕开：保留缺口，只有取得同等可核对的实时证据后才能报告完成。

## 回写、关闭和恢复

完成适用验收、远端同步和环境核对后，分别在回写前检查 `write_issue`、关闭前检查 `close_issue`，并保持 `queue-guard` 有效；两项独立授权，详见[权限规则](permissions.md#每次外部写入前检查)。只取得标签/占用授权不能评论或关单。回写前读取完整评论，优先更新或复用同一交付记录。可使用稳定标记 `personal-dev:delivery:<仓库>#<编号>:<最终SHA>` 定位本次评论；在 `issue_updated` 保存返回的链接/ID。

评论或关单请求超时、执行中断时，先重新读取评论与工单状态。已有相同评论则复用，不盲目重发；已关闭则核对依据，不重新打开再关闭。仍开放且所有条件满足时继续关单；无法确认结果或内容有新失败反馈时保持“待核对/待修复”。若用户已停止，保存剩余动作，不为了完成记录继续外部写入。

关闭后必须再次读取远端工单，确认 `state=closed`。新版普通单与自动队列都通过当前 owner 的 `queue-finish` 完成；此前未建立远端占用的遗留单才允许以下兼容核验：

```sh
python3 .agents/skills/personal-dev/scripts/pda.py delivery-check --project . --issue 23 --commit FULL_40_CHARACTER_FINAL_SHA
```

该命令检查五项证据存在且绑定最终提交，再实时检查提交可达远端集成分支、读取工单确认关闭；仅本次返回 `verified` 才算脚本核验成功。它不执行测试、不判断证据文字真实性、不授予权限，也不自动推送、写评论、关单或启动服务。PR 是否实际合并及目标是否正确也不由该命令检查，须由 Agent 调用平台读取并保存证据；不得仅凭 verified 宣称 PR 已合并。最终内容、实际运行环境与工单最新评论仍由 Agent 按交付规则判断。

普通已领取工单与队列均沿用 `queue-guard` 和停止优先规则，阶段证据用 `delivery-record` 保存；先取得同提交的 accepted 和 integration_verified 后进入 ready_to_merge，再取得集成锁进入 merging，最后由 **`queue-finish` 内部执行同一完成检查**。不能改用 `delivery-check` 绕过 owner/停止控制或权限检查。旧任务缺记录时，从真实证据补齐，不重新开发或伪造验收。远端已关闭或 done 但本地仍有 current，领取/续接返回 finishing 时先核对已完成事实，在有效 owner 与续接授权下只补收尾。finish 成功才记远端 done、同步 ai-done 并清 current；标签/资源释放中断仍保留 current，重试继续原收尾，不重新执行开发。

## Worktree 收尾

完成检查成功后按[worktree 生命周期](worktree-lifecycle.md)尝试清理并保存结果。所有已领取任务在 queue-finish 清空 current 之前先把路径、分支和提交登记到主目录台账；成功后通过 queue-cleanup-guard 检查再清理，完成或记明保留原因后才领取下一单。清理失败不回滚已完成的交付或重开工单；收到用户停止则保留，不为清理重新启动队列。

## 最终回复与完成边界

每次工单交付回复必须包含：工单链接/编号、PR 链接及实际状态（直接合并则给出选择依据）、最终提交和目标分支、验收依据、工单远端状态，以及 worktree 清理结果或保留原因。状态只能写实际结果：已关闭并读回确认、待用户测试、待集成验证、待回写/关单、关单结果待核对，或用户明确暂不关闭。尚有步骤缺失时说明缺口及下一动作，不能只用“已 push、工作区干净”结束任务。

用户说“验证通过，请 push”，在已有自动收尾授权、最终版本及环境证据满足时，应继续回写、关单和读回确认；用户不必再提醒一次。必要前提缺失或请求失败时报告“代码已推送，工单收尾未完成”及具体原因。最终回复不是后台调度器；结束会话后不会自行补关单，必须在本轮完成已授权可执行的收尾，或明确保留阻碍。
