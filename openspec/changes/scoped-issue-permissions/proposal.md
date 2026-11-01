# 分离工单控制与业务操作权限

## Why

用户已允许指定工单的占用及状态写入，但运行时仍要求业务分支推送和完整工单写入开关，导致反复确认和临时扩大工程全局权限。

## What Changes

- 新增 manage_claims、update_issue_labels、close_issue；write_issue 仅创建/修改内容和评论，push_task_branch 仅业务代码。
- 在 Git 忽略的本地记录保存仓库、分支、owner、issue 精确绑定的允许/拒绝与授权依据，支持查看、撤销、按动作检查；拒绝优先。
- 单工单 worker 显式绑定 issue scope，不能通过 next、retry、转交或 watch 借用本单授权处理其他单。
- 配置读取兼容旧字段集合，缺少的新权限按 false 解释且不自动回写；协议 6 完整分发，保留工程配置与现有任务状态。

## Impact

权限模块、CLI、worker/watch 接入与配置兼容；同步规则和使用说明。并不改变 Gitea/GitHub 账号真实权限，外部工具操作仍由 Agent 遵守当前授权检查；不自动开启监听或发布业务代码。
