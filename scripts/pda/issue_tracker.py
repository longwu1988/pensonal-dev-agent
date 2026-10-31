"""Bounded read-only issue APIs. Remote bodies are untrusted data, never commands."""
import base64
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import ssl
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, HTTPSHandler, Request

from .transaction import InstallError, safe_path


def _url(value, ssh=False):
    if (not isinstance(value, str) or not value or not value.isascii()
            or any(c.isspace() or ord(c) < 32 for c in value)
            or any(c in value for c in ('\\', '?', '#', '%'))):
        raise InstallError('invalid repository URL')
    if ssh and value.startswith('git@'):
        match = re.fullmatch(r'git@([^/:]+):(.+)', value)
        if not match:
            raise InstallError('invalid repository URL')
        value = 'ssh://git@' + match[1] + '/' + match[2]
    try:
        parsed = urlsplit(value)
        allowed = ('https', 'ssh') if ssh else ('https',)
        if parsed.scheme not in allowed or not parsed.hostname:
            raise ValueError()
        if parsed.password is not None or parsed.username != ('git' if parsed.scheme == 'ssh' else None):
            raise ValueError()
        host = parsed.hostname.lower()
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) or '..' in host:
            raise ValueError()
        port = parsed.port
        if parsed.netloc.endswith(':') or (port is not None and port == 0):
            raise ValueError()
        if parsed.scheme == 'ssh' and port not in (None, 22):
            raise ValueError()
        authority = host
        if parsed.scheme == 'https' and port not in (None, 443):
            authority += ':' + str(port)
        path = parsed.path.rstrip('/')
        if path and (not path.startswith('/') or any(
                not re.fullmatch(r'[A-Za-z0-9_.-]+', part) or part in ('.', '..')
                for part in path[1:].split('/'))):
            raise ValueError()
        return 'https://' + authority, path
    except ValueError:
        raise InstallError('invalid repository URL') from None


def canonical_repository(url):
    """Normalize credential-free HTTPS and conventional Git SSH remote URLs."""
    origin, path = _url(url, ssh=True)
    if path.endswith('.git'):
        path = path[:-4]
    if len(path.split('/')) < 3 or not path.split('/')[-1] or path.split('/')[-1] in ('.', '..'):
        raise InstallError('repository URL requires owner and repository')
    return origin + path


MAX_PAGES = 100
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_CREDENTIAL_BYTES = 64 * 1024
REQUEST_TIMEOUT = 10
OPERATION_TIMEOUT = 60
PAGE_SIZE = 100


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _credential_text(value):
    if (not isinstance(value, str) or not value or not value.isascii()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise InstallError('invalid tracker authentication')
    return value


class Tracker:
    """Read one configured repository; credentials never follow remote-provided links."""

    def __init__(self, kind, repository, root: Path, credentials_path=None):
        if kind not in ('gitea', 'github'):
            raise InstallError('unsupported issue tracker')
        self.kind = kind
        self.repository = canonical_repository(repository)
        origin, path = _url(self.repository)
        parts = path[1:].split('/')
        if kind == 'github':
            if origin != 'https://github.com' or len(parts) != 2:
                raise InstallError('only public hosted GitHub repositories are supported')
            self.service = 'https://github.com'
            self.api = 'https://api.github.com/repos/' + '/'.join(parts)
        else:
            self.service = origin + ('/' + '/'.join(parts[:-2]) if len(parts) > 2 else '')
            self.api = self.service + '/api/v1/repos/' + '/'.join(parts[-2:])
        self._authorization = self._credentials(Path(root), credentials_path)

    def _token(self, token):
        token = _credential_text(token)
        if any(c.isspace() for c in token):
            raise InstallError('invalid tracker authentication')
        return ('Bearer ' if self.kind == 'github' else 'token ') + token

    def _credentials(self, root, credentials_path):
        token = os.environ.get('PDA_' + self.kind.upper() + '_TOKEN')
        if token:
            return self._token(token)
        try:
            relative = Path(credentials_path or '.local/secrets/access.json')
            if relative.is_absolute():
                relative = relative.relative_to(root.resolve())
            path = safe_path(root, relative.as_posix())
            if not path.exists():
                if credentials_path is not None:
                    raise ValueError()
                return None
            with path.open('rb') as handle:
                raw = handle.read(MAX_CREDENTIAL_BYTES + 1)
            if len(raw) > MAX_CREDENTIAL_BYTES:
                raise ValueError()
            value = json.loads(raw)
            if not isinstance(value, dict) or not isinstance(value.get('services'), dict):
                raise ValueError()
            service = value['services'].get(self.kind)
            if service is None:
                return None
            if not isinstance(service, dict):
                raise ValueError()
            if all(service.get(key) in (None, '') for key in ('token', 'username', 'password')):
                return None
            origin, path = _url(service.get('url'))
            allowed = {self.service}
            if self.kind == 'github':
                allowed.add('https://api.github.com')
            if origin + path not in allowed:
                raise ValueError()
            if service.get('token') not in (None, ''):
                return self._token(service['token'])
            if 'username' in service or 'password' in service:
                if self.kind != 'gitea':
                    raise ValueError()
                username = _credential_text(service.get('username'))
                password = _credential_text(service.get('password'))
                if ':' in username:
                    raise ValueError()
                return 'Basic ' + base64.b64encode((username + ':' + password).encode()).decode('ascii')
            return None
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
            raise InstallError('invalid tracker authentication configuration') from None

    def _budget(self):
        return [monotonic() + OPERATION_TIMEOUT, 0]

    def _remaining(self, budget):
        remaining = budget[0] - monotonic()
        if remaining <= 0:
            raise InstallError('issue tracker operation time limit exceeded')
        return min(REQUEST_TIMEOUT, remaining)

    def _request(self, suffix, budget, query=None):
        url = self.api + suffix
        if query:
            url += '?' + urlencode(query)
        headers = {'Accept': 'application/json', 'User-Agent': 'personal-dev-agent'}
        if self.kind == 'github':
            headers.update({'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
        if self._authorization:
            headers['Authorization'] = self._authorization
        request = Request(url, headers=headers, method='GET')
        try:
            opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
            with opener.open(request, timeout=self._remaining(budget)) as response:
                if response.status != 200:
                    raise InstallError('issue tracker returned an unsuccessful status')
                length = response.headers.get('Content-Length')
                if length is not None and int(length) > MAX_RESPONSE_BYTES:
                    raise InstallError('issue tracker response size limit exceeded')
                chunks, size = [], 0
                while True:
                    self._remaining(budget)
                    chunk = response.read1(min(65536, MAX_RESPONSE_BYTES - size + 1))
                    self._remaining(budget)
                    if not chunk:
                        break
                    size += len(chunk)
                    budget[1] += len(chunk)
                    if size > MAX_RESPONSE_BYTES or budget[1] > MAX_TOTAL_BYTES:
                        raise InstallError('issue tracker response size limit exceeded')
                    chunks.append(chunk)
                return json.loads(b''.join(chunks))
        except InstallError:
            raise
        except HTTPError as error:
            error.close()
            raise InstallError('issue tracker HTTP request failed') from None
        except (OSError, URLError, HTTPException, ValueError, UnicodeError, RecursionError):
            raise InstallError('issue tracker request or response failed') from None

    def _pages(self, suffix, budget, state=None):
        records = []
        for page in range(1, MAX_PAGES + 1):
            query = {'page': page, 'limit' if self.kind == 'gitea' else 'per_page': PAGE_SIZE}
            if state:
                query['state'] = state
            value = self._request(suffix, budget, query)
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                raise InstallError('invalid issue tracker list response')
            if not value:
                return records
            records.extend(value)
        raise InstallError('issue tracker pagination limit exceeded')

    def issues(self):
        """Return open issues; Gitea may include pull_request: null on them."""
        return [item for item in self._pages('/issues', self._budget(), state='open')
                if item.get('pull_request') is None and item.get('state', 'open') == 'open']

    def issue(self, number):
        """Return the issue and its complete comments_data list as untrusted data."""
        if type(number) is not int or number <= 0:
            raise InstallError('issue number must be a positive integer')
        budget = self._budget()
        suffix = '/issues/' + str(number)
        value = self._request(suffix, budget)
        if not isinstance(value, dict) or value.get('number') != number or value.get('pull_request') is not None:
            raise InstallError('invalid issue tracker issue response')
        result = dict(value)
        result['comments_data'] = self._pages(suffix + '/comments', budget)
        return result
