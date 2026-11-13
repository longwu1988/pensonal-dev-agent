# L1 轻量实施路径

仅用于 [P-patch](playbooks.md) / [P-bug](playbooks.md) / [P-ui](playbooks.md) 等 L1 短剧本。**不要**为走本路径而打开 [implementation.md](implementation.md) 全文。

适用：范围明确的单点修复或小改（文案、配置、局部逻辑、有明确同类参考的界面微调）；不改业务规则、跨模块 API 或架构。

1. **范围**：修改端已能从对话、打开目录或单端工程唯一推断时，沿用该端，不问不候。多端且无法唯一推断时先确认，或升 [P-feature](playbooks.md)。
2. **工单**：有编号时按 [issue-claims](issue-claims.md) 领取；读正文与当前相关评论即可（[issue-context](issue-context.md) L1 预算）。无编号的明确小修可不建 OpenSpec。发现规则/API/跨模块变化 → 升 P-feature。
3. **隔离**：复用当前会话已有分支或 worktree；不为每个 L1 新建隔离目录。
4. **界面**：涉及布局/样式时只读 [ui-design](ui-design.md) 门禁；不需要原型则留下视觉依据后实现。
5. **验证**：按 [testing](testing.md) 做受影响范围最小验证；未跑过的不视为已通过。
6. **交付**：用户未要求提交/合入/关单时，实现与验证后停在可续接状态。用户点名交付时改走 [P-deliver](playbooks.md)，再读收尾引用。

本文件读完即够实施；上调后再读 L2 [实施流程](implementation.md)。
