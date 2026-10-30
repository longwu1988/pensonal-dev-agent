# 最小接入使用说明

## 获取与使用

本版是草稿分支上的试验能力，尚未发布稳定 Tag。需要 Python 3.9+，仅使用标准库。文件锁使用 POSIX fcntl，当前在 macOS 验证；Linux 待实测，Windows 暂不支持。

先克隆明确的分支，审阅代码并记录 commit；后续只在工程主动选择时更新。以下在个人仓库目录执行，将占位的项目路径替换为真实的已有目录：

```sh
git clone --branch codex/development-system-v0-1 https://github.com/longwu1988/pensonal-dev-agent.git
cd pensonal-dev-agent
python3 scripts/pda.py init --project /path/to/project
python3 scripts/pda.py init --project /path/to/project --apply
python3 scripts/pda.py doctor --project /path/to/project
```

默认 init 只展示文件动作及完整差异，不创建目录或文件。--apply 在相同预检通过后写入。存在同名的非受管文件、用户修改过的受管文件、无效配置或不安全目标路径时停止；没有强制覆盖选项。

## 安装什么

| 工程位置 | 归属与行为 |
| --- | --- |
| `.agents/skills/personal-dev/` | 安装器管理的唯一 Skill 内容，含分层流程和角色 |
| `.cursor/rules/personal-dev.mdc` | 安装器管理的 Cursor 入口，只指向共享规则 |
| 根 `AGENTS.md`、`.gitignore` | 仅维护 personal-dev 标记区；区外原始字节保留 |
| `docs/agents/README.md` | 配置字段说明，安装器管理 |
| `docs/agents/project.json` | 工程自行维护；只在不存在时生成，升级保留 |
| `docs/agents/personal-dev.dependencies.json` | 固定上游候选来源，不是自动安装清单 |
| `docs/agents/personal-dev.lock.json` | 可提交的受管内容摘要；新克隆也能幂等识别 |
| `.local/agent/install/` | 本地锁与最近一次事务备份，加入 Git 忽略，不提交 |

现有应用、MCP、OpenSpec 配置、上游 skills 与业务文件不在本安装器的写入清单内。应用映射从直接子目录的 AGENTS 发现，需人工核对补充；集成分支、仓库、验证命令及环境不猜测。

安装后维护 project.json：重要选择引用决策文档，未知状态保留未知。密钥仅记外部来源，不能填写真实值。权限默认为 false，按实际授权填写；配置不覆盖当前会话或宿主限制。小程序真机、数据库环境等无法自动验证的条件继续保留缺口。

## 工具入口

两端共用工程的 `.agents/skills/`，不复制另一份技能。Codex 可显式引用 `$personal-dev`，Cursor 可使用 `/personal-dev`，也可直接要求按个人开发入口处理任务。目录和调用方式参考 [Codex 官方说明](https://learn.chatgpt.com/docs/build-skills)、[Cursor Skills](https://cursor.com/help/customization/skills) 与 [Cursor Rules](https://cursor.com/help/customization/rules)（核对于 2026-10-30）。

本轮仅完成文件生成、脚本和合成行为检查，不能据此宣称两端自动发现与业务执行已验收。新会话中确认入口可发现，再按阶段 3 用真实任务验证；未出现时检查实际宿主配置。

## 更新、冲突与恢复

更新个人仓库至自己选定的 commit，再运行 init 预览。只有现有受管文件仍与 lock 中的上次安装摘要相同才更新；用户配置保留，AGENTS 区外新增规则保留。若自行修改 Skill 或管理区，先审阅 diff，人工合并处理；不要删除 lock 或伪造摘要绕过冲突。

写入前生成本地备份，每个文件原子替换。正常失败留下 prepared 状态，后续安装要求先恢复：

```sh
python3 scripts/pda.py recover --project /path/to/project
python3 scripts/pda.py recover --project /path/to/project --apply
```

恢复只针对最近一次有变化的安装，预检所有内容和权限后回到该次写入前；重复安装无变化时不覆盖备份。安装后用户再编辑目标文件或权限时，恢复会拒绝覆盖，需人工处理。恢复中再次失败可重试。保留既有目录和本地日志；恢复了原 .gitignore 后，本地日志可能不再被忽略，仍不得提交。

备份可能含原有规则与配置，权限为 0600，按本地敏感文件管理。升级成功会替换上一次备份，长期版本回退依赖 Git 历史；不承诺跨文件断电原子性或与外部编辑器并发修改的安全合并。

## 检查范围与限制

doctor 只读取工程配置、本地候选入口摘要、MCP 配置文件是否存在及 PATH 中 OpenSpec 是否存在；不执行配置里的命令、不访问远端、不检查 Drone。报告不包含 MCP 配置正文，避免输出其中凭据。

入口摘要匹配不代表完整上游依赖、账号授权或行为验证通过。候选引用没有复制上游正文，各来源及许可见 [core profile](../profiles/core.json)；组合冲突由 [能力选择](../skills/personal-dev/references/providers.md) 明确处理。

本阶段不提供 npm 包、上游自动安装、原生子代理配置、夜间调度或自动合并/打 Tag。只安装单项 Skill 不等于完整接入；不要先用其他工具安装同名文件再强行让本安装器接管。

验证命令为 `python3 -m unittest discover -s tests -v`。案例与实际边界见 [行为记录](../tests/behavior.md)。
