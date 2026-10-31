# 工单队列实施计划

使用 subagent-driven-development 分工并独立审查。Python 标准库；仅合成数据、临时 bare Git 仓库和模拟 HTTP，不连接真实业务服务。

- [x] 先写 `tests/test_issue_tracker.py`，验证分页、PR 排除、仓库解析、认证来源、重定向和失败；执行失败基线，再实现 `scripts/pda/issue_tracker.py`。
- [x] 先写 `tests/test_issue_queue.py`，用临时 Git 仓库验证默认关闭、start/stop/resume、排序、阻塞、远端精确锁竞争、停止请求优先、失败保留和完成证据；执行失败基线，再实现 `scripts/pda/issue_queue.py`。
- [x] 修改 `scripts/pda.py` 增加队列命令，安装器 RUNTIME 纳入两模块并升协议 2；增加安装分发、独立入口运行、旧协议拒绝及恢复回归。
- [x] 新增 `skills/personal-dev/references/issue-queue.md`，接入 SKILL 与工单流程；明确用户开始/结束、空队列、等待确认、需求不可信、分支/服务/凭据边界和重入规则。同步 README 与安装说明。
- [x] 运行 `python3 -m unittest discover -s tests -v`、两处 OpenSpec validate、相对引用和 `git diff --check`；独立规格/质量审查，修正阻塞后再次验证。
- [x] 本地提交候选并报告实测与未验证边界；不擅自开启真实工程队列。发布按用户明确授权进行。

- [x] 补充统一工单上下文规则：全部分页评论、实际读图、缺口与变更复核；双平台图片引用保留测试、独立五项行为复核及安装分发验证。
