# Scoped Issue Permissions Implementation Plan

> 执行使用 subagent-driven-development 与 test-driven-development；用户已批准拆分及单次授权方向。以已有 OpenSpec 目录保存计划，避免重复目录。

**Goal:** 只授权本单占用/标签即可修复验证，不开放业务推送或影响其他会话。
**Architecture:** 独立本地 Permissions 记录 + worker issue scope + 工程新字段保守读取；外部动作显式检查，运行时仅执行其真实支持的动作。
**Tech Stack:** Python 标准库、现有 Git/HTTP 客户端、unittest。

- [x] 1. 新建 scripts/pda/permissions.py 与 tests/test_permissions.py：先 RED 再实现绑定、allow/deny、撤销、损坏/路径保护与不修改全局配置。
- [x] 2. 修改 config.py、project.json，新增字段 false 并兼容旧配置；CLI permissions-* 命令、queue-start --issue 与 worker 范围守卫；先补针对 #6/其他会话/其他单的失败测试。
- [x] 3. 将 worker/watch 的旧权限检查改为控制权限，守卫重读权限；watch 不使用单工单授权，转交不复制来源授权。更新协议6完整分发及迁移/中断恢复测试。
- [x] 4. 统一权限规则及示例，删除临时开启业务推送的要求，保留单次指令和外部真实权限边界。
- [x] 5. 全量测试、严格OpenSpec、安装与链接检查、独立规格/代码审查，修复发现后本地提交；未经本轮另行请求不发布远端。
