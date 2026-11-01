## ADDED Requirements

### Requirement: 控制记录独立授权
系统 SHALL 使用 manage_claims 与 update_issue_labels 控制占用及状态写入，不要求 push_task_branch 或 write_issue。close_issue 单独控制关单；现有外部业务操作遵循对应授权。

#### Scenario: 只允许领取指定单
- **WHEN** 用户明确允许 #6 占用和状态更新但禁止代码推送、PR、合并、关单
- **THEN** 工具允许本单控制操作，工程业务权限保持原值，不反复请求同一授权。

### Requirement: 单次授权精确绑定且可撤销
系统 SHALL 将授权与仓库、集成分支、owner 和工单绑定，保存授权依据；拒绝优先，撤销不回落到全局允许，不从外部工单内容推定授权。记录是 Agent 执行约束，不是平台身份鉴权。

#### Scenario: 另一个会话或工单尝试使用授权
- **WHEN** 会话 B 或 #7 使用仅授予会话 A 的 #6 授权
- **THEN** 拒绝，不能改全局权限、换 owner 或启动批量/持续处理绕过。

### Requirement: 旧版兼容不扩大权限
系统 SHALL 保留旧工程配置原文和权限字段，缺失新字段按 false 解释，升级不自动授予新动作或启动任务。通过协议6完整源码迁移和恢复。

#### Scenario: 升级旧项目
- **WHEN** 旧配置没有控制或关闭权限
- **THEN** 仍可读取旧配置但不推导新增授权；已有明确用户授权可按范围记录，无依据才询问。
