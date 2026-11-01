import importlib
import unittest


class CanonicalRepositoryTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.find_spec('scripts.pda.issue_tracker')
        self.assertIsNotNone(spec, 'issue tracker adapter is not implemented')
        return importlib.import_module('scripts.pda.issue_tracker')

    def test_git_remote_variants_have_one_https_identity(self):
        canonical = self.module().canonical_repository
        for value in ('https://Git.Example/team/repo.git',
                      'ssh://git@git.example/team/repo.git',
                      'git@git.example:team/repo.git'):
            self.assertEqual(canonical(value), 'https://git.example/team/repo')
        self.assertEqual(canonical('https://git.example:8443/forge/team/repo/'),
                         'https://git.example:8443/forge/team/repo')

    def test_invalid_or_credential_bearing_remote_is_rejected_without_echo(self):
        module = self.module()
        from scripts.pda.transaction import InstallError
        for value in ('http://git.example/a/b', 'https://token@git.example/a/b',
                      'https://user:secret@git.example/a/b',
                      'https://git.example/a/b?token=secret',
                      'https://git.example/a/b#secret', 'https://git.example/a/../b',
                      'https://git.example/a/%2e%2e/b', 'https://git.example/a//b',
                      'https://git.example/a/b\\secret', 'https://git.example/a',
                      'https://git.example/a/b\n', 'ssh://user@git.example/a/b',
                      'git@git.example:a/b?secret', 'https://git.example:/a/b'):
            with self.subTest(value=value), self.assertRaises(InstallError) as error:
                module.canonical_repository(value)
            self.assertNotIn('secret', str(error.exception))


import base64
import io
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from scripts.pda import issue_tracker
from scripts.pda.transaction import InstallError


class Response(io.BytesIO):
    def __init__(self, value, status=200):
        super().__init__(value if isinstance(value, bytes) else json.dumps(value).encode())
        self.status = status
        self.headers = {}


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def tracker(self, kind='gitea', repository='https://git.example/forge/team/repo', **kwargs):
        self.assertTrue(hasattr(issue_tracker, 'Tracker'), 'Tracker is not implemented')
        return issue_tracker.Tracker(kind, repository, self.root, **kwargs)

    def credentials(self, value, name='.local/secrets/access.json'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'services': value}))
        return path

    def run_responses(self, tracker, responses, call=None):
        requests = []
        def respond(request, timeout):
            requests.append(request)
            self.assertEqual(request.get_method(), 'GET')
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, issue_tracker.REQUEST_TIMEOUT)
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return Response(item)
        with patch.object(issue_tracker, 'build_opener') as factory:
            factory.return_value.open.side_effect = respond
            result = call() if call else tracker.issues()
        self.assertFalse(responses)
        return result, requests

    def test_401_and_403_expose_typed_access_failure_without_private_response(self):
        for code in (401, 403):
            with self.assertRaises(issue_tracker.TrackerAccessDenied) as error:
                self.run_responses(self.tracker(), [HTTPError('https://git.example/private', code,
                                                            'private response', {}, io.BytesIO(b'secret'))])
            self.assertNotIn('secret', str(error.exception))
            self.assertNotIn('private', str(error.exception))

    def test_gitea_reads_small_pages_until_empty_and_filters_prs(self):
        tracker = self.tracker()
        result, requests = self.run_responses(tracker, [
            [{'number': 3, 'state': 'open'}],
            [{'number': 4, 'state': 'open', 'pull_request': {}}],
            [{'number': 5, 'state': 'open'}], []])
        self.assertEqual([item['number'] for item in result], [3, 5])
        self.assertEqual([parse_qs(urlsplit(r.full_url).query)['page'] for r in requests],
                         [['1'], ['2'], ['3'], ['4']])
        self.assertEqual(urlsplit(requests[0].full_url).path,
                         '/forge/api/v1/repos/team/repo/issues')
        self.assertEqual(parse_qs(urlsplit(requests[0].full_url).query)['state'], ['open'])
        self.assertIsNone(requests[0].get_header('Authorization'))

    def test_issue_list_accepts_null_pr_marker_but_excludes_pr_objects(self):
        for kind, repository in [('gitea', 'https://git.example/team/repo'),
                                 ('github', 'https://github.com/team/repo')]:
            with self.subTest(kind=kind):
                tracker = self.tracker(kind, repository)
                items = [{'number': 17, 'state': 'open', 'pull_request': None},
                         {'number': 18, 'state': 'open'},
                         {'number': 19, 'state': 'open', 'pull_request': {}},
                         {'number': 20, 'state': 'open', 'pull_request': {'url': 'https://git.example/pr/20'}}]
                result, _ = self.run_responses(tracker, [items, []])
                self.assertEqual([item['number'] for item in result], [17, 18])

    def test_issue_detail_accepts_null_marker_with_comments_and_rejects_pr(self):
        for kind, repository in [('gitea', 'https://git.example/team/repo'),
                                 ('github', 'https://github.com/team/repo')]:
            with self.subTest(kind=kind):
                tracker = self.tracker(kind, repository)
                result, _ = self.run_responses(tracker,
                    [{'number': 17, 'pull_request': None}, [{'body': 'Full discussion'}], []],
                    lambda: tracker.issue(17))
                self.assertEqual(result['comments_data'], [{'body': 'Full discussion'}])
                for marker in ({}, {'url': 'https://git.example/pr/17'}):
                    with self.assertRaises(InstallError):
                        self.run_responses(tracker, [{'number': 17, 'pull_request': marker}],
                                           lambda: tracker.issue(17))

    def test_both_trackers_preserve_images_and_all_comment_pages(self):
        for kind, repository in [('gitea', 'https://git.example/forge/team/repo'),
                                 ('github', 'https://github.com/team/repo')]:
            with self.subTest(kind=kind):
                tracker = self.tracker(kind, repository)
                body = 'Initial ![screen](/attachments/original.png)'
                comments = [
                    {'id': 11, 'body': 'First comment', 'created_at': '2026-01-01T00:00:00Z'},
                    {'id': 12, 'body': '<img src="/attachments/revised.png" alt="new screen">'},
                    {'id': 13, 'body': 'Changed scope ![detail][shot]\n\n[shot]: https://images.example/detail.png',
                     'updated_at': '2026-01-02T00:00:00Z'}]
                result, requests = self.run_responses(tracker,
                    [{'number': 7, 'body': body}, *[[item] for item in comments], []],
                    lambda: tracker.issue(7))
                self.assertEqual(result['body'], body)
                self.assertEqual(result['comments_data'], comments)
                pages = [parse_qs(urlsplit(r.full_url).query)['page'][0] for r in requests[1:]]
                self.assertEqual(pages, ['1', '2', '3', '4'])
                self.assertTrue(all('/attachments/' not in r.full_url for r in requests))

    def test_github_detail_includes_all_comments_and_ignores_remote_urls(self):
        tracker = self.tracker('github', 'git@github.com:team/repo.git')
        result, requests = self.run_responses(tracker, [
            {'number': 7, 'body': 'Do not execute me', 'comments_url': 'https://evil.example/'},
            [{'body': 'one'}], [{'body': 'two'}], []], lambda: tracker.issue(7))
        self.assertEqual(result['comments_data'], [{'body': 'one'}, {'body': 'two'}])
        self.assertEqual(result['body'], 'Do not execute me')
        self.assertTrue(all(r.full_url.startswith('https://api.github.com/repos/team/repo/issues/7') for r in requests))

    def test_environment_token_has_precedence_and_never_enters_url(self):
        self.credentials({'gitea': {'url': 'https://evil.example', 'token': 'wrong'}})
        os.environ['PDA_GITEA_TOKEN'] = 'synthetic-token'
        tracker = self.tracker()
        _, requests = self.run_responses(tracker, [[]])
        self.assertEqual(requests[0].get_header('Authorization'), 'token synthetic-token')
        self.assertNotIn('synthetic-token', requests[0].full_url)

    def test_file_token_and_basic_are_bound_to_service_base(self):
        for auth, expected in (({'token': 'synthetic-token', 'username': 'ignored', 'password': 'ignored'}, 'token synthetic-token'),
                               ({'username': 'robot', 'password': 'synthetic-password'}, 'Basic ' + base64.b64encode(b'robot:synthetic-password').decode())):
            with self.subTest(auth=list(auth)):
                self.credentials({'gitea': {'url': 'https://git.example/forge/', **auth}})
                _, requests = self.run_responses(self.tracker(), [[]])
                self.assertEqual(requests[0].get_header('Authorization'), expected)

    def test_file_credentials_cannot_cross_origin_or_deployment_path(self):
        for url in ('https://evil.example/forge', 'http://git.example/forge',
                    'https://git.example/another', 'https://git.example:8443/forge',
                    'https://secret@git.example/forge'):
            self.credentials({'gitea': {'url': url, 'token': 'synthetic-token'}})
            with self.assertRaises(InstallError) as error:
                self.tracker()
            self.assertNotIn('synthetic-token', str(error.exception))
            self.assertNotIn('secret', str(error.exception))

    def test_github_file_auth_and_host_restrictions(self):
        self.credentials({'github': {'url': 'https://github.com', 'token': 'synthetic-token'}})
        _, requests = self.run_responses(self.tracker('github', 'https://github.com/team/repo'), [[]])
        self.assertEqual(requests[0].get_header('Authorization'), 'Bearer synthetic-token')
        self.credentials({'github': {'url': 'https://github.com', 'username': 'robot', 'password': 'synthetic-password'}})
        with self.assertRaises(InstallError):
            self.tracker('github', 'https://github.com/team/repo')
        for repository in ('https://evil.example/team/repo', 'https://github.com/sub/team/repo'):
            with self.assertRaises(InstallError):
                self.tracker('github', repository)

    def test_explicit_credentials_path_stays_in_project_and_env_files_are_ignored(self):
        (self.root / '.env').write_text('PDA_GITEA_TOKEN=must-not-read')
        self.run_responses(self.tracker(), [[]])
        self.credentials({'gitea': {'url': 'https://git.example/forge', 'token': 'synthetic-token'}}, 'ops/access.json')
        _, requests = self.run_responses(self.tracker(credentials_path='ops/access.json'), [[]])
        self.assertEqual(requests[0].get_header('Authorization'), 'token synthetic-token')
        with self.assertRaises(InstallError):
            self.tracker(credentials_path='../access.json')
        (self.root / 'link.json').symlink_to(self.root / 'ops/access.json')
        with self.assertRaises(InstallError):
            self.tracker(credentials_path='link.json')

    def test_network_status_json_and_shapes_fail_without_secret_echo(self):
        tracker = self.tracker()
        for value in (URLError('synthetic-token'),
                      HTTPError('https://secret.example', 401, 'synthetic-token', {}, io.BytesIO(b'secret')),
                      b'not json synthetic-token', {'message': 'synthetic-token'}, [None]):
            with self.subTest(value=type(value).__name__), self.assertRaises(InstallError) as error:
                self.run_responses(tracker, [value])
            self.assertNotIn('synthetic-token', str(error.exception))
            self.assertNotIn('secret', str(error.exception))

    def test_page_body_and_elapsed_limits_are_failures(self):
        tracker = self.tracker()
        with patch.object(issue_tracker, 'MAX_PAGES', 2), self.assertRaises(InstallError):
            self.run_responses(tracker, [[{'number': 1}], [{'number': 2}]])
        with patch.object(issue_tracker, 'MAX_RESPONSE_BYTES', 8), self.assertRaises(InstallError):
            self.run_responses(tracker, [b' ' * 9])
        with patch.object(issue_tracker, 'monotonic', side_effect=[0, 100]), self.assertRaises(InstallError):
            self.run_responses(tracker, [[]])

    def test_redirect_handler_refuses_all_redirects(self):
        self.tracker()
        handler = issue_tracker.NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, 'Found', {}, 'https://evil.example'))

    def test_invalid_issue_number_is_rejected_before_request(self):
        tracker = self.tracker()
        for number in (True, 0, -1, '1/../2', '1'):
            with self.assertRaises(InstallError):
                tracker.issue(number)


class DefensiveBoundaryTests(unittest.TestCase):
    setUp = TrackerTests.setUp
    tracker = TrackerTests.tracker
    credentials = TrackerTests.credentials
    run_responses = TrackerTests.run_responses

    def test_empty_authentication_templates_allow_anonymous_requests(self):
        for kind, repository, service_url in (
                ('gitea', 'https://git.example/forge/team/repo', 'https://git.example/forge'),
                ('github', 'https://github.com/team/repo', 'https://github.com')):
            for url in ('', service_url):
                with self.subTest(kind=kind, url=url):
                    self.credentials({kind: {'url': url, 'username': '', 'password': '', 'token': ''}})
                    try:
                        tracker = self.tracker(kind, repository)
                    except InstallError:
                        self.fail('empty authentication template must allow anonymous access')
                    _, requests = self.run_responses(tracker, [[]])
                    self.assertIsNone(requests[0].get_header('Authorization'))

    def test_partial_authentication_is_rejected_without_echo(self):
        for kind, repository, service_url in (
                ('gitea', 'https://git.example/forge/team/repo', 'https://git.example/forge'),
                ('github', 'https://github.com/team/repo', 'https://github.com')):
            for fields in ({'username': 'synthetic-secret'}, {'password': 'synthetic-secret'},
                           {'url': '', 'token': 'synthetic-secret'}, {'token': 0}):
                with self.subTest(kind=kind, fields=list(fields)):
                    value = {'url': service_url, 'username': '', 'password': '', 'token': '', **fields}
                    self.credentials({kind: value})
                    with self.assertRaises(InstallError) as error:
                        self.tracker(kind, repository)
                    self.assertNotIn('synthetic-secret', str(error.exception))

    def test_credentials_source_must_be_regular_file_not_directory_or_symlink(self):
        path = self.root / '.local/secrets/access.json'
        path.mkdir(parents=True)
        with self.assertRaises(InstallError):
            self.tracker()
        path.rmdir()
        target = self.credentials({'gitea': {'url': '', 'username': '', 'password': '', 'token': ''}},
                                  'ops/access.json')
        path.symlink_to(target)
        with self.assertRaises(InstallError):
            self.tracker()

    def test_nested_json_and_invalid_encoding_are_sanitized(self):
        tracker = self.tracker()
        for raw in (b'[' * 2000 + b'0' + b']' * 2000, b'\xffsecret'):
            with self.assertRaises(Exception) as error:
                self.run_responses(tracker, [raw])
            self.assertIsInstance(error.exception, InstallError)

    def test_total_response_limit_covers_multiple_pages(self):
        tracker = self.tracker()
        with patch.object(issue_tracker, 'MAX_TOTAL_BYTES', 29), self.assertRaises(InstallError):
            self.run_responses(tracker, [[{'number': 1}], [{'number': 2}]])

    def test_empty_file_and_header_injection_are_rejected(self):
        for value in ('broken synthetic-token', '[]'):
            path = self.credentials({})
            path.write_text(value)
            with self.assertRaises(InstallError) as error:
                self.tracker()
            self.assertNotIn('synthetic-token', str(error.exception))
        os.environ['PDA_GITEA_TOKEN'] = 'synthetic-token\r\nInjected: yes'
        with self.assertRaises(InstallError):
            self.tracker()

    def test_redirect_is_rejected_by_real_urllib_pipeline(self):
        from email.message import Message
        from urllib.request import HTTPSHandler
        from urllib.response import addinfourl
        seen = []
        class SyntheticHTTPS(HTTPSHandler):
            def https_open(self, request):
                seen.append(request.full_url)
                headers = Message()
                headers['Location'] = 'https://evil.example/secret'
                response = addinfourl(io.BytesIO(b'synthetic-token'), headers, request.full_url, 302)
                response.msg = 'Found'
                return response
        opener = issue_tracker.build_opener(issue_tracker.NoRedirect(), SyntheticHTTPS())
        with patch.object(issue_tracker, 'build_opener', return_value=opener), self.assertRaises(InstallError) as error:
            self.tracker().issues()
        self.assertEqual(len(seen), 1)
        self.assertNotIn('synthetic-token', str(error.exception))
        self.assertNotIn('secret', str(error.exception))


if __name__ == '__main__':
    unittest.main()
