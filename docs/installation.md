# 最小接入使用说明

## 获取与使用

本版从 `main` 提供试验能力，尚未发布稳定 Tag。需要 Python 3.9+，仅使用标准库。文件锁使用 POSIX fcntl，当前在 macOS 验证；Linux 待实测，Windows 暂不支持。

先克隆明确的分支，审阅代码并记录 commit；后续只在工程主动选择时更新。以下在个人仓库目录执行，将占位的项目路径替换为真实的已有目录：

```sh
git clone --branch main https://github.com/longwu1988/pensonal-dev-agent.git
cd pensonal-dev-agent
python3 scripts/pda.py init --project /path/to/project
python3 scripts/pda.py init --project /path/to/project --apply
python3 scripts/pda.py doctor --project /path/to/project
```

默认 init 只展示文件动作及完整差异，不创建目录或文件。--apply 在相同预检通过后写入。存在同名的非受管文件、用户修改过的受管文件、无效配置或不安全目标路径时停止；没有强制覆盖选项。

## 安装后如何使用

安装完成后打开工程的 `docs/agents/README.md`，按“第一次使用”示例开始新会话。源码中的同一份[使用指南](../templates/project-guide.md)会随安装和升级分发，末尾保留工程配置字段说明。此指南是受管文件，项目个性配置维护在 `project.json` 和非受管工程规则中。

## 安装什么

| 工程位置 | 归属与行为 |
| --- | --- |
| `.agents/skills/personal-dev/` | 安装器管理的唯一 Skill 内容，含分层流程、角色和 scripts 更新、队列及工单收尾运行时 |
| `.cursor/rules/personal-dev.mdc` | 安装器管理的 Cursor 入口，只指向共享规则 |
| 根 `AGENTS.md`、`.gitignore` | 仅维护 personal-dev 标记区；区外原始字节保留 |
| `docs/agents/README.md` | 使用指南、对话示例及配置字段说明，安装器管理 |
| `docs/agents/project.json` | 工程自行维护；只在不存在时生成，升级保留 |
| `docs/agents/personal-dev.dependencies.json` | 固定上游候选来源，不是自动安装清单 |
| `docs/agents/personal-dev.lock.json` | 可提交的受管内容摘要及来源 commit；新克隆也能幂等识别 |
| `.local/agent/install/` | 本地锁与最近一次事务备份，加入 Git 忽略，不提交 |
| `.local/agent/updates/` | 当前电脑/工程的检查时间、候选、稍后提醒及跳过状态，不提交 |
| `.local/agent/worktree-registry/` | Agent 按任务维护的 worktree 清理台账与恢复定位；忽略于 Git，安装器不预建、不删除 |
| `.local/agent/watch/` | 持续授权、宿主调度绑定及下一检查时间；本机私有，不随 Git 同步 |
| `.local/agent/queue/` | 同仓库主工作目录的队列状态与本机锁；不提交，不随 Git 同步 |

现有应用、MCP、OpenSpec 配置、上游 skills 与业务文件不在本安装器的写入清单内。应用映射从直接子目录的 AGENTS 发现，需人工核对补充；集成分支、仓库、验证命令及环境不猜测。

安装后维护 project.json：重要选择引用决策文档，未知状态保留未知。`environment.secrets` 只记录 Agent 操作凭据来源，默认使用当前工程的 `.local/secrets/access.json`；应用运行凭据继续由各自配置管理。具体边界与使用按[凭据用途与来源](../skills/personal-dev/references/credentials.md)处理，安装器不自动创建敏感文件。权限默认为 false，按实际授权填写；配置不覆盖当前会话或宿主限制。小程序真机、数据库环境等无法自动验证的条件继续保留缺口。

## 工具入口

两端共用工程的 `.agents/skills/`，不复制另一份技能。Codex 可显式引用 `$personal-dev`，Cursor 可使用 `/personal-dev`，也可直接要求按个人开发入口处理任务。目录和调用方式参考 [Codex 官方说明](https://learn.chatgpt.com/docs/build-skills)、[Cursor Skills](https://cursor.com/help/customization/skills) 与 [Cursor Rules](https://cursor.com/help/customization/rules)（核对于 2026-10-30）。

本轮仅完成文件生成、脚本和合成行为检查，不能据此宣称两端自动发现与业务执行已验收。新会话中确认入口可发现，再按阶段 3 用真实任务验证；未出现时检查实际宿主配置。

## 更新、冲突与恢复

更新个人仓库至自己选定的 commit，再运行 init 预览。只有现有受管文件仍与 lock 中的上次安装摘要相同才更新；用户配置保留，AGENTS 区外新增规则保留。若自行修改 Skill 或管理区，先审阅 diff，人工合并处理；不要删除 lock 或伪造摘要绕过冲突。

### 按工程检查与选择更新

首次从审阅过的源码运行 `init --apply` 会分发独立更新运行时，后续电脑只要克隆包含安装结果的业务工程并有 Python 3.9+，无需预先克隆个人源码即可检查。旧安装没有运行时或 source 字段时，先用完整安装器升级一次；安装源缺少 Git 信息或分发文件有未提交改动时 commit 为 null，不能据此判断更新。干净源码的版本识别需要 Git。

具体命令和 Agent 提示规则见[版本检查与更新选择](../skills/personal-dev/references/updates.md)。首次启用新任务由 Agent 执行 check-update，默认 24 小时最多联网检查一次；推荐延后更新，不因沉默自动安装。稍后提醒和跳过状态按本机工程保存，安装版本按工程保存在可提交 lock；选择更新不同时替其他工程升级。

版本固定到 `longwu1988/pensonal-dev-agent` 的 main 完整 commit。开发分支领先 main 时报告 ahead；分叉报告 diverged，不自动降级。检查失败继续本地工作，可显式 `--force` 重查。GitHub 公开 API 无账号依赖但有请求限额，网络和限额问题均不阻塞业务任务；本工具不改 Git 全局配置或自动配置代理。

update 默认下载到系统临时目录并预览，只有 `--apply` 写入。当前本地运行时负责安装，不执行下载的 Python；校验固定提交的 Git blob 摘要、常规文件路径、体积和协议，临时下载退出即清理。本版新增 `notifications.py` 和固定 WAV 资源，当前更新协议为 4。协议 1/2/3 updater 会拒绝不完整更新，需要从审阅过、固定提交的完整源码再执行一次 `init` 预览和 `init --apply`；保留已有 project.json、区外规则、权限、queue/delivery/watch 状态，不删除 lock 绕过冲突。已有持续任务升级前先停止本地模式和宿主调度并保存检查点，升级后用户明确继续才重新绑定。迁移或恢复中断时使用完整协议 4 源码执行 `python3 scripts/pda.py recover --project /path/to/project --apply`，旧事务模块不识别新增文件，不能依赖半更新的入口。后续协议 4 兼容更新可用工程内 updater。

安装事务包含运行时和来源记录，因此 recover 会同时恢复版本；它不会恢复提醒偏好、队列或工单收尾状态。更新期间 main 前进不改变用户选定候选，工程配置继续由工程维护。应用后新任务加载新规则，宿主自动发现、热重载及跨工具会话仍需单独验收。安装 runtime 提供更新检查、更新选择、恢复、队列控制、工单收尾检查及本地固定语音播放；init 和 doctor 仍从完整源码目录调用。

写入前生成本地备份，每个文件原子替换。正常失败留下 prepared 状态，后续安装要求先恢复：

```sh
python3 scripts/pda.py recover --project /path/to/project
python3 scripts/pda.py recover --project /path/to/project --apply
```

恢复只针对最近一次有变化的安装，预检所有内容和权限后回到该次写入前；重复安装无变化时不覆盖备份。安装后用户再编辑目标文件或权限时，恢复会拒绝覆盖，需人工处理。恢复中再次失败可重试。保留既有目录和本地日志；恢复了原 .gitignore 后，本地日志可能不再被忽略，仍不得提交。

备份可能含原有规则与配置，权限为 0600，按本地敏感文件管理。升级成功会替换上一次备份，长期版本回退依赖 Git 历史；不承诺跨文件断电原子性或与外部编辑器并发修改的安全合并。

## 工单队列接入

完整安装当前协议 4 后，按[工单队列](../skills/personal-dev/references/issue-queue.md)核对仓库、集成分支、权限与认证，再由用户明确开始。安装本身保持队列关闭；不自动创建后台任务；持续模式需另行明确开启并绑定宿主调度。命令、领取条件、远端控制分支副作用及恢复方式均以该文档为准。

HTTP 读取支持 Gitea 与 github.com，使用 `PDA_GITEA_TOKEN` / `PDA_GITHUB_TOKEN` 或工程明确配置的 Agent 操作凭据来源；Git 推送使用现有 Git 登录。MCP 内部 OAuth 不会自动传给 CLI，工单评论、标签和关单仍由 Agent 使用已授权工具完成。此能力尚待真实仓库及两端会话验收。

## 检查范围与限制

doctor 只读取工程配置、本地候选入口摘要、MCP 配置文件是否存在及 PATH 中 OpenSpec 是否存在；不执行配置里的命令、不访问远端、不检查 CI 或运行打包。delivery 按实际配置报告，未选择 CI 不列为接入缺失；兼容字段 drone_status_from_project 仅在 provider 为 drone 时返回其状态，否则为 null。报告不包含 MCP 配置正文，避免输出其中凭据。

入口摘要匹配不代表完整上游依赖、账号授权或行为验证通过。候选引用没有复制上游正文，各来源及许可见 [core profile](../profiles/core.json)；组合冲突由 [能力选择](../skills/personal-dev/references/providers.md) 明确处理。

本阶段不提供 npm 包、上游自动安装、原生子代理配置、夜间调度或自动合并/打 Tag。只安装单项 Skill 不等于完整接入；不要先用其他工具安装同名文件再强行让本安装器接管。

验证命令为 `python3 -m unittest discover -s tests -v`。案例与实际边界见 [行为记录](../tests/behavior.md)。

## 工单收尾检查更新

普通工单和队列共用[收尾记录与完成检查](../skills/personal-dev/references/completion.md)。收尾命令自协议 2 起提供，没有新增工程配置字段；当前包含持续模式和音频提醒的版本为协议 4，旧工程按上面的完整源码迁移流程接入。更新后在新任务/新会话读取新规则。已有进行中的队列缺少收尾记录时，从真实验收、Git 和工单证据补齐后继续，不删除队列状态重新领取。

收尾记录存于主工作目录 `.local/agent/delivery/`，各 worktree 共用。更新与重复安装保留记录；它是本机进度，不随 Git 分发到其他电脑。换电脑或仅安装 Skill 时按规则从可信工单与远端恢复，不将缺失记录猜成已完成。

## 持续检查接入

按[持续检查模式](../skills/personal-dev/references/issue-watch.md)执行开启、宿主调度绑定、首次验证及停止流程。`watch-start` 仅保存 pending 授权；`watch-bind` 不会创建调度；必须实际配置宿主 heartbeat 并读回激活状态。当前提供 Codex 桌面工具适配指引，Cursor 调度未验证；真实宿主持续运行仍需试点，不把合成测试当作已完成实机验收。

## Worktree 清理接入

[worktree 生命周期规则](../skills/personal-dev/references/worktree-lifecycle.md)及队列 `queue-cleanup-guard` 自协议 3 起提供；当前含音频资源的协议 4 仍保留这套流程，旧工程按前述完整源码方式迁移。新任务加载规则后由 Agent 登记并执行 Git/宿主工具清理，安装器不会删除任何现存 worktree，也不会自动建立历史清理授权或后台任务。台账不受安装事务管理，更新/恢复保留已有记录。
