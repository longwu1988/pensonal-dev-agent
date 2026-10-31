# 工程接入配置

`project.json` 是工程自行维护的输入；安装器升级保留它。路径以工程根目录为基准，未知值用 null 或空列表，不能把未知写成验证通过。

- `project`：项目名称、工程维护的阶段标签、集成分支、工单仓库；初始化用 discovery，可随进度改为 existing、test-deployed 等非空单行标签。阶段仅为描述，不授予部署或其他操作权限；分支不会默认取当前任务分支。
- `apps`：每项提供 name、path、rules 与 validation。validation 是命令/环境说明列表，安装器不会执行。兼容已有工程的 name/directory/test（可选 build）简写，只在内存中映射为标准结构，不重写原文件；简写命令的环境标为 unverified，不能据此认定已经通过验证。
- `decisions`：已确认技术栈与架构决策的文档路径；新工程在开发前确认，既有工程先沿用。
- `worktree`：优先原生机制，fallback 为工程约定的隔离目录；数据库与端口另行隔离。
- `figma`：具体文件/节点引用与状态；配置存在不代表授权或连接成功。
- `delivery`：Drone + Tag；status 可为 unverified 或 user-confirmed，evidence 记录用户确认依据。用户确认已完成时不安排重复核查；每次实际打包仍检查结果。
- `permissions`：仅记录工程事先授予的动作范围，true 必须有用户授权依据；不覆盖宿主限制和当前会话指令。未获授权的初始值为 false。用户明确采用自动收尾流程后，将 push_task_branch、create_pr、write_issue、merge 记录为 true，并在工程规则中保留授权依据；push_tag、deploy 仍分别授权。当前明确指令优先于旧配置，已有授权不重复询问。
- `environment`：记录测试环境条件；`secrets` 仅表示 Agent 操作凭据来源，默认指向当前工程的 `.local/secrets/access.json`，不是应用运行密钥的统一路径。应用继续使用各自 `.env`、配置或环境注入；禁止在 project.json 填写真实值。保存、忽略规则、权限及 worktree 使用见工程内 `.agents/skills/personal-dev/references/credentials.md`；已有明确外部来源仍保留。
- `knowledge`：审核后知识与本地报告位置。本版未提供自动调度，schedule_enabled 必须为 false。

各端专用规范继续保留在原位置。任务从工程根目录的 `.agents/skills/personal-dev/SKILL.md` 进入，按需读取其 references。复用上游前核对 `personal-dev.dependencies.json` 中来源；doctor 只检查本地存在与候选入口摘要，不证明完整依赖、宿主调用或远端连接可用。
