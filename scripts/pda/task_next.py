"""Read-only next step for one issue. Does not claim, test, merge, or write state."""
from .issue_queue import Delivery, INTEGRATION_NOTE, configuration, git, main_project
from .issue_workers import WorkerQueue
from .transaction import InstallError

ASK = '需要新的决定时，先在当前回复写出「待你确认」，再播放提示音。本命令看不到聊天正文。'
GUIDE = {
    'claimed': ('references/implementation.md', '核对验收条件、集成分支和修改端。修改端未知时先写「待你确认」。'),
    'planning': ('references/planning.md', '范围已明确则进入实现。仍有关键未知项时先写「待你确认」。'),
    'implementing': ('references/implementation.md', '在任务 worktree 完成实现。然后只跑受影响代码的单元测试。'),
    'testing': ('references/testing.md', '把单元测试命令和结果写入 accepted。没有测试可跑时写明无单元测试，留给用户验收。'),
    'waiting_user': ('references/planning.md', '等待已经展示的确认。不重复播放提示音，不把沉默写成验收通过。'),
    'reviewing': ('references/roles.md', '重要变更做独立审查。审查没有阻塞后准备串行合入。'),
    'ready_to_merge': ('references/local-validation.md', '取得该集成分支的集成锁后再合入。其他 worktree 继续等待。'),
    'merging': ('references/issue-claims.md', '完成这一次合入、同步和回写后再释放集成锁。'),
    'blocked': ('references/issue-queue.md', '按已记录的阻塞原因处理。未恢复前不领取下一单。'),
    'done': ('references/worktree-lifecycle.md', '核对关单读回，再检查本任务 worktree 是否可以回收。'),
}
DELIVERY_GUIDE = {
    'accepted': ('references/testing.md', '记录单元测试命令和结果，或写明无单元测试，留给用户验收。'),
    'integration_verified': ('references/local-validation.md', '写明单元测试仍覆盖即将合入的代码树，并且构建验收留给用户。'),
    'remote_synced': ('references/pull-requests.md', '同步远端集成分支，并保存 PR 或直接合并的读回结果。'),
    'environment_restored': ('references/local-validation.md', '本单没有切换运行环境时，记录未改动。'),
    'issue_updated': ('references/completion.md', '回写并关闭工单。回复写明单元测试结果、合入提交，以及构建验收留给用户。'),
}


def _quiet(root, *args):
    try:
        return git(root, *args)
    except InstallError:
        return None


def _git_facts(root):
    porcelain = _quiet(root, 'status', '--porcelain')
    return {
        'branch': _quiet(root, 'rev-parse', '--abbrev-ref', 'HEAD'),
        'head': _quiet(root, 'rev-parse', 'HEAD'),
        'dirty': None if porcelain is None else bool(porcelain),
    }


def _current(root, owner, issue):
    if owner:
        state = WorkerQueue(root, owner=owner).status()
        current = state.get('current') or {}
        if issue is not None and current.get('number') not in (None, issue):
            raise InstallError('owner current issue does not match --issue')
        number = issue if issue is not None else current.get('number')
        if current.get('number') == number:
            return number, current.get('stage'), current.get('commit'), None
        return number, None, None, None
    if issue is not None:
        return issue, None, None, None
    currents = []
    for state in WorkerQueue(root).status().get('workers', []):
        current = state.get('current')
        if current:
            currents.append((state.get('owner'), current))
    if len(currents) > 1:
        return None, None, None, [item[0] for item in currents]
    if len(currents) == 1:
        owner_name, current = currents[0]
        return current.get('number'), current.get('stage'), current.get('commit'), None
    return None, None, None, None


def task_next(root, owner=None, issue=None):
    root = main_project(root)
    facts = _git_facts(root)
    number, stage, commit, owners = _current(root, owner, issue)
    base = {
        'status': 'ok', 'issue': number, 'step': stage, 'owner': owner,
        'can_merge': False, 'missing': [], 'git': facts,
        'ask': ASK, 'merge': INTEGRATION_NOTE,
    }
    if owners:
        base.update(status='ambiguous', step='claim', missing=['owner'],
                    next='多个会话各有当前工单。指定 --owner 后再看下一步。',
                    read='references/issue-claims.md', owners=owners)
        return base
    if number is None:
        base.update(status='idle', step='claim', missing=['issue'],
                    next='没有当前工单。用户给出编号后领取；没有编号时先创建工单。',
                    read='references/issue-claims.md')
        return base
    try:
        _, _, repository, branch = configuration(root)
        delivery = Delivery(root, repository, branch).status(number)
    except InstallError as exc:
        base.update(status='needs_config', missing=['project configuration'],
                    next='先补齐工程的工单仓库和集成分支配置，再继续这个工单。',
                    read='references/planning.md', config_error=str(exc))
        return base
    record = delivery.get('record') or {}
    steps = record.get('steps') or {}
    missing = list(delivery.get('missing') or [])
    evidence_commit = record.get('commit')
    if commit and evidence_commit and commit != evidence_commit:
        missing = ['evidence_commit_mismatch', *missing]
    covered = bool(steps.get('accepted') and steps.get('integration_verified')
                   and evidence_commit and 'evidence_commit_mismatch' not in missing
                   and stage not in ('waiting_user', 'blocked', 'done'))
    if stage in GUIDE:
        read, nxt = GUIDE[stage]
    else:
        read, nxt = DELIVERY_GUIDE['issue_updated']
    if stage in (None, 'testing', 'reviewing') or (stage in ('ready_to_merge', 'merging') and not covered):
        focus = next((DELIVERY_GUIDE[item] for item in missing if item in DELIVERY_GUIDE), None)
        if focus:
            read, nxt = focus
    if stage == 'waiting_user':
        base['ask'] = '等待已经展示的确认。不重复播放提示音。'
    base.update(step=stage or 'delivery', next=nxt, read=read, missing=missing,
                can_merge=covered, evidence_commit=evidence_commit)
    return base
