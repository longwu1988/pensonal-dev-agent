"""Synthetic label API contracts; never contact a real tracker."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from scripts.pda import issue_tracker
from scripts.pda.transaction import InstallError


class Response(io.BytesIO):
    def __init__(self, value, status=200):
        super().__init__(b'' if status == 204 else json.dumps(value).encode())
        self.status, self.headers = status, {}


class LabelAPI:
    def __init__(self, kind, target_exists=True):
        self.kind = kind
        self.labels = {1: 'bug', 2: 'ai-ready', 3: 'p1'}
        if target_exists:
            self.labels[4] = 'ai-in-progress'
        self.applied = {1, 2, 3}
        self.requests = []
        self.fail = None
        self.extra_on_readback = False
        self.changed = False
        self.pr = None
        self.create_race = False

    def items(self, ids):
        return [{'id': i, 'name': self.labels[i]} for i in sorted(ids)]

    def open(self, request, timeout):
        self.requests.append(request)
        assert 0 < timeout <= issue_tracker.REQUEST_TIMEOUT
        path = urlsplit(request.full_url).path.split('/team/repo')[-1]
        method = request.get_method()
        if method != 'GET' and self.fail:
            raise self.fail
        body = json.loads(request.data) if request.data else None
        page = parse_qs(urlsplit(request.full_url).query).get('page', ['1'])[0]
        if path == '/issues/7' and method == 'GET':
            return Response({'number': 7, 'pull_request': self.pr})
        if path == '/labels' and method == 'GET':
            return Response(self.items(self.labels) if page == '1' else [])
        if path == '/labels' and method == 'POST':
            assert body['color'] == ('#1d76db' if self.kind == 'gitea' else '1d76db')
            self.labels[4] = body['name']
            if self.create_race:
                raise HTTPError(request.full_url, 422, 'race', {}, io.BytesIO())
            return Response({'id': 4, 'name': body['name']}, 201)
        if path == '/issues/7/labels' and method == 'GET':
            if self.kind == 'gitea':
                # Gitea's issue-label endpoint returns the entire list, no pagination.
                assert not urlsplit(request.full_url).query
            if self.extra_on_readback and self.changed:
                self.applied.add(2)
            return Response(self.items(self.applied) if page == '1' else [])
        if path == '/issues/7/labels' and method == 'POST':
            assert body == {'labels': [4 if self.kind == 'gitea' else 'ai-in-progress']}
            self.applied.add(4)
            # Another actor adds an unrelated label during our transition.
            self.labels[5] = 'customer-added'
            self.applied.add(5)
            self.changed = True
            return Response(self.items(self.applied))
        if path.startswith('/issues/7/labels/') and method == 'DELETE':
            assert path == '/issues/7/labels/' + ('2' if self.kind == 'gitea' else 'ai-ready')
            self.applied.discard(2)
            self.changed = True
            return Response(self.items(self.applied), 204 if self.kind == 'gitea' else 200)
        raise AssertionError((method, path, body))


class IssueLabelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def tracker(self, kind):
        repo = 'https://github.com/team/repo' if kind == 'github' else 'https://git.example/forge/team/repo'
        return issue_tracker.Tracker(kind, repo, Path(self.temp.name))

    def run_api(self, kind, api):
        tracker = self.tracker(kind)
        self.assertTrue(hasattr(tracker, 'set_stage'), 'set_stage is not implemented')
        with patch.object(issue_tracker, 'build_opener', return_value=api):
            result = tracker.set_stage(7, 'ai-in-progress')
        return result

    def test_reuses_label_preserves_unrelated_concurrent_labels_and_reads_back(self):
        for kind in ('gitea', 'github'):
            with self.subTest(kind=kind):
                api = LabelAPI(kind)
                self.run_api(kind, api)
                self.assertEqual(api.applied, {1, 3, 4, 5})
                methods = [r.get_method() for r in api.requests]
                self.assertNotIn('PUT', methods)
                self.assertEqual(methods.count('POST'), 1)
                self.assertEqual(methods.count('DELETE'), 1)
                self.assertEqual(methods[-1], 'GET')
                # Repeated synchronization has no writes.
                api.requests.clear()
                self.run_api(kind, api)
                self.assertEqual({r.get_method() for r in api.requests}, {'GET'})

    def test_missing_repository_label_is_created_once_and_creation_race_reconciles(self):
        for kind in ('gitea', 'github'):
            for race in (False, True):
                with self.subTest(kind=kind, race=race):
                    api = LabelAPI(kind, target_exists=False)
                    api.create_race = race
                    self.run_api(kind, api)
                    self.assertEqual(api.applied, {1, 3, 4, 5})
                    self.assertEqual(sum(r.get_method() == 'POST' for r in api.requests), 2)

    def test_readback_disagreement_is_not_success(self):
        api = LabelAPI('gitea')
        api.extra_on_readback = True
        with self.assertRaises(InstallError):
            self.run_api('gitea', api)

    def test_mutation_failure_and_timeout_are_not_success(self):
        for failure in (URLError('private'), TimeoutError('private'),
                        HTTPError('https://private', 403, 'private', {}, io.BytesIO()),
                        HTTPError('https://private', 500, 'private', {}, io.BytesIO())):
            api = LabelAPI('gitea')
            api.fail = failure
            with self.assertRaises(InstallError) as error:
                self.run_api('gitea', api)
            self.assertNotIn('private', str(error.exception))
            self.assertEqual(api.applied, {1, 2, 3})

    def test_invalid_number_stage_and_pr_cannot_write(self):
        tracker = self.tracker('gitea')
        self.assertTrue(hasattr(tracker, 'set_stage'), 'set_stage is not implemented')
        for number, label in ((True, 'ai-ready'), (0, 'ai-ready'), (7, 'bug'), (7, [])):
            with patch.object(issue_tracker, 'build_opener') as opener, self.assertRaises(InstallError):
                tracker.set_stage(number, label)
            opener.assert_not_called()
        api = LabelAPI('gitea')
        api.pr = {}
        with self.assertRaises(InstallError):
            self.run_api('gitea', api)
        self.assertTrue(all(r.get_method() == 'GET' for r in api.requests))

    def test_all_eight_existing_stages_are_read_only_when_already_synchronized(self):
        stages = ('ai-ready', 'ai-in-progress', 'ai-testing', 'ai-waiting-user',
                  'ai-ready-to-merge', 'ai-merging', 'ai-done', 'ai-blocked')
        for kind in ('gitea', 'github'):
            for stage in stages:
                with self.subTest(kind=kind, stage=stage):
                    api = LabelAPI(kind)
                    api.labels = {1: 'bug', 3: 'p1', 4: stage}
                    api.applied = {1, 3, 4}
                    with patch.object(issue_tracker, 'build_opener', return_value=api):
                        self.tracker(kind).set_stage(7, stage)
                    self.assertTrue(all(r.get_method() == 'GET' for r in api.requests))

    def test_label_shape_pagination_and_response_bounds_fail_before_mutation(self):
        tracker = self.tracker('gitea')
        for value in ({}, [None], [{'id': '../secret', 'name': 'ai-ready'}],
                      [{'id': True, 'name': 'ai-ready'}], [{'id': 1, 'name': []}]):
            with self.subTest(value=value), patch.object(issue_tracker, 'build_opener') as opener:
                opener.return_value.open.side_effect = [
                    Response({'number': 7}), Response(value), Response([])]
                with self.assertRaises(InstallError):
                    tracker.set_stage(7, 'ai-ready')
                self.assertTrue(all(call.args[0].get_method() == 'GET'
                                    for call in opener.return_value.open.call_args_list))
        for limit, value in (('MAX_PAGES', 1), ('MAX_RESPONSE_BYTES', 10), ('MAX_TOTAL_BYTES', 30)):
            api = LabelAPI('gitea')
            with patch.object(issue_tracker, limit, value), self.assertRaises(InstallError):
                self.run_api('gitea', api)
            self.assertTrue(all(r.get_method() == 'GET' for r in api.requests))

    def test_write_authentication_and_redirect_denial_follow_read_client_contract(self):
        for kind in ('gitea', 'github'):
            api = LabelAPI(kind)
            os.environ['PDA_' + kind.upper() + '_TOKEN'] = 'synthetic-token'
            self.run_api(kind, api)
            for request in api.requests:
                self.assertEqual(request.get_header('Authorization'),
                                 ('token ' if kind == 'gitea' else 'Bearer ') + 'synthetic-token')
                self.assertNotIn('synthetic-token', request.full_url)
                if request.get_method() == 'POST':
                    self.assertEqual(request.get_header('Content-type'), 'application/json')
            api = LabelAPI(kind)
            api.fail = HTTPError('https://private', 302, 'private',
                                 {'Location': 'https://evil.example'}, io.BytesIO())
            with self.assertRaises(InstallError):
                self.run_api(kind, api)
            self.assertFalse(any('evil.example' in r.full_url for r in api.requests))


if __name__ == '__main__':
    unittest.main()
