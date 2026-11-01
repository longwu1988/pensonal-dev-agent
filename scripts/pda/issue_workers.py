"""One current issue per conversation, shared remote claims across worktrees and clones."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from .issue_claims import Claims, ClaimConflict
from .issue_queue import (Queue, QueueBusy, Delivery, GitLease, STOP, REASONS,
                          _EXPLICIT_START, labels, order)
from .transaction import InstallError, atomic_write, json_bytes, read, safe_path

DIRECTORY = '.local/agent/workers'
STAGES = {'claimed': 'ai-in-progress', 'planning': 'ai-in-progress', 'implementing': 'ai-in-progress',
          'testing': 'ai-testing', 'reviewing': 'ai-testing', 'waiting_user': 'ai-waiting-user',
          'ready_to_merge': 'ai-ready-to-merge', 'merging': 'ai-merging',
          'blocked': 'ai-blocked', 'done': 'ai-done'}


def eligible(item, require_ready=True):
    names=labels(item)
    return (type(item.get('number')) is int and item['number']>0 and item.get('state')=='open'
            and item.get('pull_request') is None and not item.get('assignees') and not item.get('assignee')
            and (not require_ready or 'ai-ready' in names) and not names.intersection(set(STAGES.values())))


class WorkerQueue:
    def __init__(self, root, tracker=None, lease=None, branch=None, owner=None, claims=None):
        self.root, self.tracker = Path(root), tracker
        self.lease, self.branch, self.owner = lease or GitLease(root), branch, owner
        self.claims = claims or Claims(root, tracker.repository if tracker else None)

    def _path(self, name):
        if not isinstance(self.owner, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', self.owner):
            raise InstallError('unique conversation owner required')
        return DIRECTORY + '/' + self.owner + '/' + name

    def _stop_token(self):
        global_stop = read(self.root, STOP) or b''
        local_stop = read(self.root, self._path('stop')) if self.owner else None
        return hashlib.sha256(global_stop + b'\0' + (local_stop or b'')).hexdigest() if global_stop or local_stop else None

    def status(self):
        if not self.owner:
            paths = sorted((self.root / DIRECTORY).glob('*/state.json'))
            tasks = [WorkerQueue(self.root, owner=p.parent.name).status() for p in paths]
            return dict(version=2, enabled=False, repository=None, current=None, owner=None, workers=tasks)
        raw = read(self.root, self._path('state.json'))
        if raw is None:
            return dict(version=2, enabled=False, owner=self.owner, repository=None, integration_branch=None,
                        current=None, blocked={}, completed=[], release='released', stop_ack=None)
        try:
            state = json.loads(raw)
            if (state['version'] != 2 or state['owner'] != self.owner or type(state['enabled']) is not bool
                    or not isinstance(state['blocked'], dict) or not isinstance(state['completed'], list)):
                raise ValueError()
            if self._stop_token() != state['stop_ack']: state['enabled'] = False
            return state
        except (KeyError, ValueError, TypeError):
            raise InstallError('invalid worker state; preserve it for recovery') from None

    @contextmanager
    def _locked(self):
        path = safe_path(self.root, self._path('write.lock'))
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, 'a+b') as handle:
            try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise QueueBusy('same conversation command is running') from None
            try: yield
            finally: fcntl.flock(handle, fcntl.LOCK_UN)

    def _save(self, state):
        if self._stop_token() != state.get('stop_ack'): state['enabled'] = False
        atomic_write(self.root, self._path('state.json'), json_bytes(state), 0o600)

    def _active(self, state):
        if (not state['enabled'] or self._stop_token() != state.get('stop_ack')):
            raise InstallError('worker stopped; only explicit start may resume')
        if (not self.tracker or state['repository'] != self.tracker.repository
                or state['integration_branch'] != self.branch):
            raise ClaimConflict('worker repository or integration branch changed')
        self.claims.ensure()
        if self._stop_token() != state.get('stop_ack'): raise InstallError('stop requested')

    def _owned(self, state):
        self._active(state)
        current = state.get('current')
        if not current: raise InstallError('no current worker issue')
        record = self.claims.get('issues/' + str(current['number']))
        if (not record or record.get('owner') != self.owner or record.get('token') != current['token']
                or record.get('integration_branch') != self.branch):
            raise ClaimConflict('issue belongs to another owner or generation; do not continue')
        return record

    def start(self, expected_stop=_EXPLICIT_START):
        acknowledged = self._stop_token() if expected_stop is _EXPLICIT_START else expected_stop
        with self._locked():
            if self._stop_token() != acknowledged: raise InstallError('start authorization revoked by stop')
            old = Queue(self.root).status()
            if old.get('enabled') or old.get('current') or old.get('lease'):
                raise ClaimConflict('finish/reconcile legacy queue before enabling workers')
            state = self.status()
            if not self.tracker or not self.branch: raise InstallError('configured tracker and integration branch required')
            if state['repository'] and (state['repository'] != self.tracker.repository or state['integration_branch'] != self.branch):
                raise ClaimConflict('worker binding changed; reconcile old work')
            self.claims.ensure()
            state.update(enabled=True, repository=self.tracker.repository, integration_branch=self.branch, stop_ack=acknowledged)
            self._save(state)
            return self.status()

    def stop(self):
        target = self._path('stop') if self.owner else STOP
        atomic_write(self.root, target, uuid.uuid4().hex.encode(), 0o600)
        return self.status()

    def _sync(self, state, record):
        self._active(state)
        item = self.tracker.issue(record['number'])
        flow = labels(item).intersection(set(STAGES.values()) | {'ai-ready'})
        previous = STAGES.get(record.get('previous_stage'), 'ai-ready')
        if (item.get('pull_request') is not None or item.get('assignees') or item.get('assignee')
                or (not flow and not (state['current'].get('pending') and state['current'].get('manual'))) or not flow.issubset({STAGES[record['stage']], previous})):
            raise ClaimConflict('issue was assigned or its workflow labels changed; reconcile before writing')
        if flow != {STAGES[record['stage']]}:
            self.tracker.set_stage(record['number'], STAGES[record['stage']])
        self._active(state)
        fresh = self._owned(state)
        if fresh['_sha'] != record['_sha']: raise ClaimConflict('claim changed during label sync')
        state['current'] = {k:v for k,v in record.items() if k not in ('_sha','key','version','repository')}
        self._save(state)
        self._active(state)
        return record

    def _resume(self, state):
        current = state['current']
        if current.get('pending'):
            record = self.claims.get('issues/' + str(current['number']))
            if record is None:
                item = self.tracker.issue(current['number'])
                if not eligible(item,not current.get('manual')): raise ClaimConflict('pending claim no longer eligible; reconcile')
                self._active(state)
                record = self.claims.claim(current['number'], self.owner, current['token'], self.branch)
            if not record or (record.get('owner'), record.get('token')) != (self.owner, current['token']):
                state['current'] = None; self._save(state)
                return {'status': 'occupied'}
        record = self._owned(state)
        item = self.tracker.issue(record['number'])
        if item.get('pull_request') is not None: raise ClaimConflict('current item is not an issue')
        self._sync(state, record)
        return dict(status='finishing' if item.get('state') == 'closed' or record['stage'] == 'done' else 'resume',
                    issue=item, checkpoint=state['current'])

    def _claim(self, state, item, manual=False):
        number = item['number']
        token = uuid.uuid4().hex
        # Persist intent before the remote write so ambiguous responses remain recoverable.
        state['current'] = dict(number=number, token=token, stage='claimed', branch=None, worktree=None, commit=None, pending=True, manual=manual)
        self._save(state); self._active(state)
        record = self.claims.claim(number, self.owner, token, self.branch)
        if record is None:
            state['current'] = None; self._save(state)
            return None
        self._active(state)
        # Recheck eligibility after winning the CAS, before labels or implementation.
        fresh = self.tracker.issue(number)
        if not eligible(fresh,not manual):
            raise ClaimConflict('issue eligibility changed after claim; retain ownership and reconcile')
        self._sync(state, record)
        return dict(status='claimed', issue=fresh, checkpoint=state['current'])

    def next(self):
        with self._locked():
            state = self.status(); self._active(state)
            if state['current']:
                result = self._resume(state)
                if result['status'] != 'occupied': return result
            old = Queue(self.root).status()
            candidates = sorted((x for x in self.tracker.issues() if eligible(x)
                and x['number'] not in old['completed'] and str(x['number']) not in old['blocked']), key=order)
            for item in candidates:
                self._active(state)
                if self.claims.get('issues/' + str(item['number'])): continue
                fresh = self.tracker.issue(item['number'])
                if not eligible(fresh): continue
                result = self._claim(state, fresh)
                if result: return result
            state.update(enabled=False, release='released'); self._save(state)
            return dict(status='empty', queue=state)

    def claim(self, number):
        if type(number) is not int or number <= 0: raise InstallError('positive issue number required')
        with self._locked():
            state=self.status(); self._active(state)
            if state['current']:
                if state['current']['number'] == number: return self._resume(state)
                raise ClaimConflict('finish current issue before claiming another')
            record = self.claims.get('issues/' + str(number))
            if record and record.get('owner') == self.owner and record.get('handoff_from'):
                state['current'] = dict(number=number,token=record['token'])
                self._save(state)
                return self._resume(state)
            if record: raise ClaimConflict('issue already owned or completed')
            item=self.tracker.issue(number)
            if not eligible(item,False): raise InstallError('issue must be open, unassigned and without another workflow state')
            result=self._claim(state,item,manual=True)
            if result is None: raise ClaimConflict('issue was claimed concurrently')
            return result

    def guard(self):
        with self._locked():
            state=self.status(); record=self._owned(state)
            self._sync(state,record)
            if record['stage'] == 'merging' and not self.claims.resource_owned('integration:'+self.branch,self.owner,record['token']):
                raise ClaimConflict('integration resource missing; stop merge')
            return state

    def cleanup_guard(self):
        with self._locked():
            state=self.status(); self._active(state)
            if state['current']: raise InstallError('finish current issue before worktree cleanup')
            return state

    def _ready(self, record, commit):
        if not commit or not re.fullmatch('[0-9a-f]{40}',commit): raise InstallError('validated full commit required')
        proof=Delivery(self.root,self.tracker.repository,self.branch).status(record['number'])['record']
        if not proof or proof['commit']!=commit or not all(proof['steps'].get(k) for k in ('accepted','integration_verified')):
            raise InstallError('record acceptance/review and integration evidence for this commit first')

    def checkpoint(self, stage, branch=None, worktree=None, commit=None):
        if stage not in STAGES or stage in ('done','blocked'): raise InstallError('use finish/block for terminal stages')
        if commit is not None and not re.fullmatch('[0-9a-f]{40}',commit): raise InstallError('full commit SHA required')
        for text in (branch,worktree):
            if text is not None and (not text or not text.isprintable() or len(text)>1000): raise InstallError('invalid checkpoint locator')
        with self._locked():
            state=self.status(); record=self._owned(state)
            if record['stage'] in ('done','blocked'):
                raise InstallError('terminal claim requires finish/retry, not development checkpoints')
            self._sync(state, record)  # Complete an interrupted label transition before advancing.
            changes={k:v for k,v in dict(branch=branch,worktree=worktree,commit=commit).items() if v is not None}
            if stage in ('ready_to_merge','merging'): self._ready(record,commit or record.get('commit'))
            if stage=='merging':
                if record['stage'] not in ('ready_to_merge','merging'): raise InstallError('enter ready_to_merge before merging')
                record=self._resource(state,record,'integration:'+self.branch,True)
            elif record['stage']=='merging':
                record=self._resource(state,record,'integration:'+self.branch,False)
            if stage=='waiting_user' or (record['stage'] in ('ready_to_merge','merging') and stage not in ('ready_to_merge','merging')):
                accepted_commit = record.get('commit')
                if accepted_commit:
                    Delivery(self.root,self.tracker.repository,self.branch).record(record['number'],accepted_commit,
                        'waiting_user','acceptance invalidated by stage '+stage)
            record=self.claims.update(record,previous_stage=record['stage'],stage=stage,**changes)
            self._sync(state,record)
            return state

    def _resource(self,state,record,name,acquire):
        resources=list(record.get('resources',[]))
        if acquire:
            if name not in resources:
                resources.append(name)
                record=self.claims.update(record,resources=resources)
            self._active(state)
            if not self.claims.acquire_resource(name,self.owner,record['token']):
                record=self.claims.update(record,resources=[x for x in resources if x!=name])
                raise ClaimConflict('shared resource busy; remain at current stage')
        else:
            self.claims.release_resource(name,self.owner,record['token'])
            record=self.claims.update(record,resources=[x for x in resources if x!=name])
        self._active(state)
        return record

    def resource(self,name,acquire):
        environment=isinstance(name,str) and name.startswith('environment:') and bool(name[12:])
        integration=not acquire and name=='integration:'+str(self.branch)
        if not environment and not integration:
            raise InstallError('use environment:NAME or explicitly release a blocked integration resource')
        with self._locked():
            state=self.status(); record=self._owned(state)
            if integration and record['stage']!='blocked': raise InstallError('integration release requires blocked reconciliation')
            record=self._resource(state,record,name,acquire)
            self._sync(state,record)
            return state

    def _release_resources(self,state,record):
        for name in list(record.get('resources',[])):
            record=self._resource(state,record,name,False)
        return record

    def block(self,reason):
        if reason not in REASONS: raise InstallError('unknown blocking reason')
        with self._locked():
            state=self.status(); record=self._owned(state)
            if record['stage']=='done': raise InstallError('completed claim cannot be blocked')
            self._sync(state, record)
            record=self.claims.update(record,previous_stage=record['stage'],stage='blocked',reason=reason)
            self._sync(state,record)
            if record.get('resources'):
                raise InstallError('restore and explicitly release shared resources before skipping blocked issue')
            state['blocked'][str(record['number'])]=state['current']
            state['current']=None; self._save(state)
            return state

    def retry(self,number):
        with self._locked():
            state=self.status(); self._active(state)
            if state['current'] and state['current']['number'] != number: raise InstallError('finish current issue first')
            record=self.claims.get('issues/'+str(number))
            if not record or record['owner']!=self.owner or record['stage'] not in ('blocked','done'):
                raise ClaimConflict('only explicit retry of an owned blocked/completed issue is allowed')
            if record.get('resources'): raise InstallError('restore and release resources before retry')
            if state['current'] and state['current']['token'] != record['token']:
                raise ClaimConflict('retry ownership token changed')
            item=self.tracker.issue(number)
            if item.get('state')!='open' or item.get('pull_request') is not None or item.get('assignees') or item.get('assignee'):
                raise InstallError('restore open unassigned issue before retry')
            flow=labels(item).intersection(set(STAGES.values()) | {'ai-ready'})
            if flow not in ({'ai-ready'}, {STAGES[record['stage']]}):
                raise ClaimConflict('retry requires ai-ready or the recorded terminal label')
            previous='ready' if flow=={'ai-ready'} else record['stage']
            delivery=Delivery(self.root,self.tracker.repository,self.branch)
            proof=delivery.status(number)['record']
            if proof:
                delivery.record(number,proof['commit'],'waiting_user','acceptance invalidated by explicit retry')
            state['current']=dict(number=number,token=record['token']); self._save(state)
            record=self.claims.update(record,previous_stage=previous,stage='claimed',reason=None,commit=None)
            self._sync(state,record)
            return state

    def finish(self,commit,evidence):
        if not evidence or not evidence.isprintable() or len(evidence)>1000: raise InstallError('evidence locator required')
        with self._locked():
            state=self.status(); record=self._owned(state)
            if record['stage'] not in ('merging','done'): raise InstallError('complete merging workflow before finishing')
            Delivery(self.root,self.tracker.repository,self.branch).check(record['number'],commit,self.tracker,self.lease)
            self._active(state)
            if record['stage']!='done':
                record=self.claims.update(record,previous_stage=record['stage'],stage='done',commit=commit,evidence=evidence)
            self._sync(state,record)
            record=self._release_resources(state,record)
            if record['number'] not in state['completed']: state['completed'].append(record['number'])
            state.update(current=None,last_completion=dict(number=record['number'],commit=commit,evidence=evidence))
            self._save(state)
            return state


    def transfer(self, target, evidence):
        if (not isinstance(target,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',target)
                or target==self.owner or not evidence or not evidence.isprintable() or len(evidence)>1000):
            raise InstallError('different target owner and explicit handoff evidence required')
        with self._locked():
            state=self.status()
            if state['enabled']: raise InstallError('stop original worker before explicit transfer')
            current=state.get('current')
            if not current: raise InstallError('no current issue to transfer')
            if state['repository']!=self.tracker.repository or state['integration_branch']!=self.branch:
                raise ClaimConflict('worker binding changed')
            self.claims.ensure()
            record=self.claims.get('issues/'+str(current['number']))
            handoff=dict(owner=self.owner,token=current['token'])
            if record and record.get('owner')==target and record.get('handoff_from')==handoff:
                pass  # Recover a successful CAS whose local acknowledgement was interrupted.
            elif (not record or record.get('owner')!=self.owner or record.get('token')!=current['token']):
                raise ClaimConflict('claim ownership changed')
            else:
                if record['stage']=='done' or record.get('resources'):
                    raise InstallError('finish terminal cleanup or restore/release resources before transfer')
                record=self.claims.update(record,owner=target,token=uuid.uuid4().hex,handoff_from=handoff,
                                         handoff_evidence=evidence)
            state['current']=None
            state['last_transfer']=dict(number=record['number'],target_owner=target,evidence=evidence)
            self._save(state)
            return dict(status='transferred',issue=record['number'],target_owner=target,
                        branch=record.get('branch'),worktree=record.get('worktree'))
