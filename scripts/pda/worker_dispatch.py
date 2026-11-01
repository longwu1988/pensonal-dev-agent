"""CLI routing for per-conversation workers; legacy recovery remains explicit."""
from .issue_queue import (Queue, Delivery, GitLease, STOP, DIRECTORY as LEGACY_DIRECTORY,
                          configuration, main_project, git, validate_delivery_storage)
from .issue_workers import WorkerQueue, DIRECTORY
from .issue_claims import Claims
from .issue_tracker import Tracker
from .transaction import InstallError, safe_path


def validate_storage(root, worker):
    for directory in (DIRECTORY, LEGACY_DIRECTORY):
        if git(root,'ls-files','--',directory): raise InstallError('worker/queue state must not be Git-tracked')
    paths=[STOP]
    if worker.owner: paths += [worker._path(name) for name in ('state.json','stop','write.lock')]
    for path in paths:
        safe_path(root,path)
        git(root,'check-ignore','--quiet','--',path)


def validate_checkpoint_storage(root, repository, branch, record, stage):
    if record and record.get('commit') and (stage == 'waiting_user' or
            (record.get('stage') in ('ready_to_merge', 'merging') and
             stage not in ('ready_to_merge', 'merging'))):
        # Invalidation writes the accepted record commit, not the requested new commit.
        validate_delivery_storage(root, Delivery(root, repository, branch),
                                  record['number'], record['commit'])


def dispatch(root,args):
    root=main_project(root)
    worker=WorkerQueue(root,owner=args.owner)
    action=args.action.split('-',1)[1]
    delivery_action=args.action.startswith('delivery-')
    if action=='status' and not delivery_action: return worker.status()
    if action in ('stop','legacy-stop'):
        validate_storage(root,worker)
        return Queue(root).stop() if action=='legacy-stop' else worker.stop()
    config,settings,repository,branch=configuration(root)
    if delivery_action:
        delivery=Delivery(root,repository,branch)
        if action=='status':
            if args.issue is not None: return delivery.status(args.issue)
            safe_path(root,'.local/agent/delivery/write.lock')
            numbers=sorted(int(p.stem) for p in (root/'.local/agent/delivery').glob('*.json') if p.stem.isdigit())
            return dict(status='inventory',tasks=[delivery.status(n) for n in numbers])
        validate_delivery_storage(root,delivery,args.issue,args.commit if action=='record' else None)
        if action=='record': return delivery.record(args.issue,args.commit,args.stage,args.evidence)
        old=Queue(root).status()
        tasks=WorkerQueue(root).status()['workers']
        if any(s.get('current',{}).get('number')==args.issue for s in [old]+tasks if s.get('current')):
            raise InstallError('current issue must use queue-finish with its owner')
        if delivery.status(args.issue)['record'] is None: raise InstallError('missing delivery record')
    if action == 'transfer' and not args.apply:
        return dict(status='preview', project=str(root), repository=repository, integration_branch=branch,
                    source_owner=args.owner, target_owner=args.target_owner,
                    effect='transfer the stopped source worker current issue to the target owner; retain task checkpoints',
                    needs=['explicit user transfer', 'source stopped and shared resources released',
                           'Git/API write access', 'push_task_branch and write_issue permissions'])
    if action == 'start' and not args.apply:
        return dict(status='preview',project=str(root),repository=repository,integration_branch=branch,
                    label='ai-ready',effect='per-issue remote claims, compatibility gate and stage labels; may trigger branch CI',
                    needs=['explicit user start','Git/API write access','push_task_branch and write_issue permissions'])
    if not delivery_action:
        if any(config.get('permissions',{}).get(k) is not True for k in ('push_task_branch','write_issue')):
            if action not in ('start','transfer') and not worker.status()['enabled']: raise InstallError('queue is stopped')
            raise InstallError('record queue permissions before remote claim/label writes')
        validate_storage(root,worker)
        if action not in ('start','transfer') and not worker.status()['enabled']: raise InstallError('queue is stopped')
        if action == 'checkpoint':
            # Reject unsafe known local targets before any tracker or remote access.
            validate_checkpoint_storage(root, repository, branch, worker.status().get('current'), args.stage)
        if action == 'retry':
            delivery = Delivery(root, repository, branch)
            proof = delivery.status(args.issue)['record']
            if proof:
                # Retry clears acceptance on the existing proof commit, without changing revision.
                validate_delivery_storage(root, delivery, args.issue, proof['commit'])
    credentials=config.get('environment',{}).get('secrets')
    if credentials in (None,'','.local/secrets/access.json','external-controlled-storage'): credentials=None
    worker.tracker=Tracker(settings['kind'],repository,root,credentials_path=credentials)
    worker.lease,worker.branch,worker.claims=GitLease(root,repository),branch,Claims(root,repository)
    if delivery_action:
        if worker.claims.get('issues/'+str(args.issue)):
            raise InstallError('remote claimed issue must use owner queue-finish')
        return delivery.check(args.issue,args.commit,worker.tracker,worker.lease)
    if action=='start': return worker.start()
    if action=='transfer': return worker.transfer(args.target_owner,args.evidence)
    if action=='next': return worker.next()
    if action=='claim': return worker.claim(args.issue)
    if action=='guard': return worker.guard()
    if action=='cleanup-guard': return worker.cleanup_guard()
    if action=='checkpoint':
        # The remote stage/commit can be newer when a prior label sync was interrupted.
        record = worker._owned(worker.status())
        validate_checkpoint_storage(root, repository, branch, record, args.stage)
        return worker.checkpoint(args.stage,args.branch,args.worktree,args.commit)
    if action=='resource-acquire': return worker.resource(args.resource,True)
    if action=='resource-release': return worker.resource(args.resource,False)
    if action=='block': return worker.block(args.reason)
    if action=='retry': return worker.retry(args.issue)
    if action=='finish':
        current=worker.status()['current']
        if current: validate_delivery_storage(root,Delivery(root,repository,branch),current['number'])
        return worker.finish(args.commit,args.evidence)
    raise InstallError('unknown worker action')
