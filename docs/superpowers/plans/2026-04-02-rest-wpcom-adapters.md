# REST API & WordPress.com API Adapters — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build adapter classes for the WordPress REST API and WordPress.com API so the agent workflow uses tested Python code instead of improvised curl commands.

**Architecture:** Two standalone adapter classes (`RestApiAdapter`, `WpcomAdapter`) plus a factory function (`create_adapter()`). No base class — these are stable, write-once code. Each adapter normalizes its API's quirks into a common output format matching the existing `WpCliAdapter`.

**Tech Stack:** Python 3 stdlib only (`urllib.request`, `json`, `html`, `re`, `base64`). Tests use `unittest` + `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-04-02-rest-wpcom-adapters-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `lib/adapters/__init__.py` | Create | `create_adapter(config)` factory function |
| `lib/adapters/rest_api_adapter.py` | Create | REST API + App Passwords adapter |
| `lib/adapters/wpcom_adapter.py` | Create | WordPress.com / Jetpack API adapter |
| `lib/adapters/wp_cli_adapter.py` | Modify | Add `update_category()`, `get_default_category()` |
| `tests/test_rest_api_adapter.py` | Create | Tests for REST adapter |
| `tests/test_wpcom_adapter.py` | Create | Tests for WP.com adapter |
| `tests/test_factory.py` | Create | Tests for `create_adapter()` factory |
| `agents/export.md` | Modify | Reference `create_adapter()` as preferred path |
| `agents/apply.md` | Modify | Reference `create_adapter()` as preferred path |
| `AGENTS.md` | Modify | Update adapter layer section |

---

## Task 1: Factory Function + WpCliAdapter Parity Methods

**Files:**
- Create: `lib/adapters/__init__.py`
- Modify: `lib/adapters/wp_cli_adapter.py`
- Create: `tests/test_factory.py`

- [ ] **Step 1: Create `lib/adapters/__init__.py` with factory function**

```python
def create_adapter(config):
    """Return the appropriate adapter instance for the given config."""
    method = config['connection']['method']
    if method in ('wp-cli-ssh', 'wp-cli-local'):
        from .wp_cli_adapter import WpCliAdapter
        return WpCliAdapter(config)
    elif method == 'rest-api':
        from .rest_api_adapter import RestApiAdapter
        return RestApiAdapter(config)
    elif method == 'wpcom-api':
        from .wpcom_adapter import WpcomAdapter
        return WpcomAdapter(config)
    raise ValueError(f'Unknown connection method: {method}')
```

- [ ] **Step 2: Add `update_category()` and `get_default_category()` to `WpCliAdapter`**

Add these two methods at the end of the `WpCliAdapter` class in `lib/adapters/wp_cli_adapter.py`:

```python
    def update_category(self, term_id, fields):
        """Update a category's name, slug, or description."""
        args = ['term', 'update', str(term_id), 'category']
        for key, value in fields.items():
            args.append(f'--{key}={value}')
        return self._run_command(args)

    def get_default_category(self):
        """Get the term ID of the site's default category."""
        output = self._run_command(['option', 'get', 'default_category'])
        return int(output.strip())
```

- [ ] **Step 3: Write factory tests in `tests/test_factory.py`**

```python
"""Tests for the adapter factory function."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from adapters import create_adapter
from adapters.wp_cli_adapter import WpCliAdapter


class TestCreateAdapter(unittest.TestCase):
    """Tests for create_adapter() factory routing."""

    def test_wp_cli_ssh(self):
        config = {'connection': {'method': 'wp-cli-ssh', 'ssh_user': 'root',
                                 'ssh_host': 'example.com', 'wp_path': '/var/www/html'}}
        adapter = create_adapter(config)
        self.assertIsInstance(adapter, WpCliAdapter)

    def test_wp_cli_local(self):
        config = {'connection': {'method': 'wp-cli-local', 'wp_path': '/var/www/html'}}
        adapter = create_adapter(config)
        self.assertIsInstance(adapter, WpCliAdapter)

    def test_rest_api(self):
        config = {'connection': {'method': 'rest-api', 'api_url': 'https://example.com/wp-json',
                                 'username': 'admin', 'app_password': 'xxxx'}}
        adapter = create_adapter(config)
        from adapters.rest_api_adapter import RestApiAdapter
        self.assertIsInstance(adapter, RestApiAdapter)

    def test_wpcom_api(self):
        config = {'connection': {'method': 'wpcom-api', 'site_id': '123',
                                 'access_token': 'tok'}}
        adapter = create_adapter(config)
        from adapters.wpcom_adapter import WpcomAdapter
        self.assertIsInstance(adapter, WpcomAdapter)

    def test_unknown_method_raises(self):
        config = {'connection': {'method': 'carrier-pigeon'}}
        with self.assertRaises(ValueError) as ctx:
            create_adapter(config)
        self.assertIn('carrier-pigeon', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
```

Note: The `test_rest_api` and `test_wpcom_api` tests will fail until those adapters exist. That's expected — they'll pass after Tasks 2 and 4.

- [ ] **Step 4: Run the WP-CLI and unknown-method tests**

```bash
python3 -m unittest tests.test_factory.TestCreateAdapter.test_wp_cli_ssh tests.test_factory.TestCreateAdapter.test_wp_cli_local tests.test_factory.TestCreateAdapter.test_unknown_method_raises -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Run all existing tests to verify nothing broke**

```bash
python3 -m unittest discover tests -v
```

Expected: All 49 existing tests PASS, plus 3 new ones.

- [ ] **Step 6: Commit**

```bash
git add lib/adapters/__init__.py lib/adapters/wp_cli_adapter.py tests/test_factory.py
git commit -m "Add adapter factory function and WpCliAdapter parity methods"
```

---

## Task 2: REST API Adapter — HTTP Layer and Category Operations

**Files:**
- Create: `lib/adapters/rest_api_adapter.py`
- Create: `tests/test_rest_api_adapter.py`

- [ ] **Step 1: Write `tests/test_rest_api_adapter.py` with tests for `_request()`, `list_categories()`, category mutations, and error handling**

```python
"""Tests for the WordPress REST API adapter."""

import base64
import io
import json
import os
import sys
import unittest
from http.client import HTTPResponse
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from adapters.rest_api_adapter import RestApiAdapter


def _mock_response(body, status=200, headers=None):
    """Create a mock HTTP response that behaves like urllib's response."""
    data = json.dumps(body).encode() if not isinstance(body, bytes) else body
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = data
    resp.getheader = lambda name, default=None: (headers or {}).get(name, default)
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


CONFIG = {
    'connection': {
        'method': 'rest-api',
        'api_url': 'https://example.com/wp-json',
        'username': 'admin',
        'app_password': 'ABCD 1234 EFGH 5678',
    }
}


class TestRestApiAuth(unittest.TestCase):
    """Tests that requests carry correct Basic auth headers."""

    @patch('urllib.request.urlopen')
    def test_basic_auth_header(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response([])
        adapter = RestApiAdapter(CONFIG)
        adapter.list_categories()

        req = mock_urlopen.call_args[0][0]
        auth = req.get_header('Authorization')
        expected = base64.b64encode(b'admin:ABCD 1234 EFGH 5678').decode()
        self.assertEqual(auth, f'Basic {expected}')


class TestRestApiListCategories(unittest.TestCase):
    """Tests for list_categories() normalization and pagination."""

    @patch('urllib.request.urlopen')
    def test_normalizes_id_to_term_id(self, mock_urlopen):
        """REST API returns 'id'; adapter must emit 'term_id'."""
        api_cats = [{'id': 5, 'name': 'Tech', 'slug': 'tech',
                     'description': 'Technology posts', 'count': 42, 'parent': 0}]
        mock_urlopen.return_value = _mock_response(api_cats,
                                                   headers={'X-WP-TotalPages': '1'})
        adapter = RestApiAdapter(CONFIG)
        cats = adapter.list_categories()

        self.assertEqual(cats[0]['term_id'], 5)
        self.assertNotIn('id', cats[0])
        self.assertEqual(cats[0]['name'], 'Tech')
        self.assertEqual(cats[0]['count'], 42)

    @patch('urllib.request.urlopen')
    def test_paginates_using_total_pages_header(self, mock_urlopen):
        """Fetches all pages when X-WP-TotalPages > 1."""
        page1 = [{'id': 1, 'name': 'A', 'slug': 'a', 'description': '', 'count': 1, 'parent': 0}]
        page2 = [{'id': 2, 'name': 'B', 'slug': 'b', 'description': '', 'count': 2, 'parent': 0}]
        mock_urlopen.side_effect = [
            _mock_response(page1, headers={'X-WP-TotalPages': '2'}),
            _mock_response(page2, headers={'X-WP-TotalPages': '2'}),
        ]
        adapter = RestApiAdapter(CONFIG)
        cats = adapter.list_categories()

        self.assertEqual(len(cats), 2)
        self.assertEqual(cats[0]['term_id'], 1)
        self.assertEqual(cats[1]['term_id'], 2)
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch('urllib.request.urlopen')
    def test_empty_site_returns_empty_list(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response([],
                                                   headers={'X-WP-TotalPages': '0'})
        adapter = RestApiAdapter(CONFIG)
        cats = adapter.list_categories()
        self.assertEqual(cats, [])


class TestRestApiCategoryMutations(unittest.TestCase):
    """Tests for create, update, and delete category operations."""

    @patch('urllib.request.urlopen')
    def test_create_category_returns_term_id(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({'id': 99, 'name': 'New Cat', 'slug': 'new-cat'})
        adapter = RestApiAdapter(CONFIG)
        term_id = adapter.create_category('New Cat', 'new-cat', 'A new category')

        self.assertEqual(term_id, 99)
        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        self.assertEqual(body['name'], 'New Cat')
        self.assertEqual(body['slug'], 'new-cat')
        self.assertEqual(body['description'], 'A new category')

    @patch('urllib.request.urlopen')
    def test_update_category_sends_fields(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({'id': 5})
        adapter = RestApiAdapter(CONFIG)
        adapter.update_category(5, {'description': 'Updated desc'})

        req = mock_urlopen.call_args[0][0]
        self.assertIn('/categories/5', req.full_url)
        body = json.loads(req.data)
        self.assertEqual(body['description'], 'Updated desc')

    @patch('urllib.request.urlopen')
    def test_delete_category_uses_force(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({'deleted': True})
        adapter = RestApiAdapter(CONFIG)
        adapter.delete_category(5)

        req = mock_urlopen.call_args[0][0]
        self.assertIn('/categories/5', req.full_url)
        self.assertIn('force=true', req.full_url)
        self.assertEqual(req.method, 'DELETE')

    @patch('urllib.request.urlopen')
    def test_get_default_category(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({'default_category': 7})
        adapter = RestApiAdapter(CONFIG)
        self.assertEqual(adapter.get_default_category(), 7)

    @patch('urllib.request.urlopen')
    def test_set_post_categories(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({'id': 123})
        adapter = RestApiAdapter(CONFIG)
        adapter.set_post_categories(123, [1, 5, 9])

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        self.assertEqual(body['categories'], [1, 5, 9])


class TestRestApiErrorHandling(unittest.TestCase):
    """Tests for HTTP error responses."""

    @patch('urllib.request.urlopen')
    def test_401_includes_status_in_message(self, mock_urlopen):
        from urllib.error import HTTPError
        error_body = json.dumps({'code': 'rest_cannot_access', 'message': 'Unauthorized'}).encode()
        mock_urlopen.side_effect = HTTPError(
            'https://example.com/wp-json/wp/v2/categories',
            401, 'Unauthorized', {}, io.BytesIO(error_body))
        adapter = RestApiAdapter(CONFIG)

        with self.assertRaises(Exception) as ctx:
            adapter.list_categories()
        self.assertIn('401', str(ctx.exception))

    @patch('urllib.request.urlopen')
    def test_html_error_page_doesnt_crash(self, mock_urlopen):
        """Misconfigured servers may return HTML instead of JSON."""
        from urllib.error import HTTPError
        html_body = b'<html><body>500 Internal Server Error</body></html>'
        mock_urlopen.side_effect = HTTPError(
            'https://example.com/wp-json/wp/v2/categories',
            500, 'Internal Server Error', {}, io.BytesIO(html_body))
        adapter = RestApiAdapter(CONFIG)

        with self.assertRaises(Exception) as ctx:
            adapter.list_categories()
        self.assertIn('500', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail (adapter doesn't exist yet)**

```bash
python3 -m unittest tests.test_rest_api_adapter -v 2>&1 | head -5
```

Expected: `ModuleNotFoundError: No module named 'adapters.rest_api_adapter'`

- [ ] **Step 3: Implement `lib/adapters/rest_api_adapter.py` — HTTP layer and category operations**

```python
"""WordPress REST API adapter using Application Passwords."""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request


class RestApiAdapter:
    """
    Adapter for WordPress REST API with Application Passwords.
    Requires WordPress 5.6+ with Application Passwords enabled.
    """

    def __init__(self, config):
        self.config = config
        conn = config['connection']
        self.api_url = conn['api_url'].rstrip('/')
        credentials = f"{conn['username']}:{conn['app_password']}"
        self._auth = 'Basic ' + base64.b64encode(credentials.encode()).decode()

    def _request(self, method, path, data=None):
        """Make an authenticated request to the REST API."""
        url = f'{self.api_url}{path}'
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header('Authorization', self._auth)
        if body is not None:
            req.add_header('Content-Type', 'application/json')

        try:
            resp = urllib.request.urlopen(req)
            return resp
        except urllib.error.HTTPError as e:
            error_body = e.read().decode(errors='replace')
            raise Exception(
                f'REST API error {e.code} {method} {path}: {error_body}'
            ) from None

    def _get_json(self, path):
        """GET request, return parsed JSON."""
        resp = self._request('GET', path)
        return json.loads(resp.read()), resp

    def list_categories(self):
        """List all categories, paginating as needed."""
        categories = []
        page = 1
        while True:
            data, resp = self._get_json(
                f'/wp/v2/categories?per_page=100&page={page}'
            )
            for cat in data:
                categories.append({
                    'term_id': cat['id'],
                    'name': cat['name'],
                    'slug': cat['slug'],
                    'description': cat.get('description', ''),
                    'count': cat.get('count', 0),
                    'parent': cat.get('parent', 0),
                })
            total_pages = int(resp.getheader('X-WP-TotalPages', '1'))
            if page >= total_pages:
                break
            page += 1
        return categories

    def create_category(self, name, slug, description=''):
        """Create a new category. Returns the new term ID."""
        resp = self._request('POST', '/wp/v2/categories', {
            'name': name, 'slug': slug, 'description': description,
        })
        return json.loads(resp.read())['id']

    def update_category(self, term_id, fields):
        """Update a category's fields (name, slug, description)."""
        self._request('POST', f'/wp/v2/categories/{term_id}', fields)

    def delete_category(self, term_id):
        """Delete a category. Requires force=true for REST API."""
        self._request('DELETE', f'/wp/v2/categories/{term_id}?force=true')

    def set_post_categories(self, post_id, category_ids):
        """Set the categories for a post."""
        self._request('POST', f'/wp/v2/posts/{post_id}', {
            'categories': category_ids,
        })

    def get_default_category(self):
        """Get the term ID of the site's default category."""
        data, _ = self._get_json('/wp/v2/settings')
        return data['default_category']
```

Note: `export_posts()` is added in Task 3 — this task covers the HTTP layer and all non-export operations.

- [ ] **Step 4: Run the REST adapter tests**

```bash
python3 -m unittest tests.test_rest_api_adapter -v
```

Expected: All tests PASS.

- [ ] **Step 5: Run the factory test for rest-api**

```bash
python3 -m unittest tests.test_factory.TestCreateAdapter.test_rest_api -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add lib/adapters/rest_api_adapter.py tests/test_rest_api_adapter.py
git commit -m "Add REST API adapter with category operations and tests"
```

---

## Task 3: REST API Adapter — `export_posts()` with HTML Stripping

**Files:**
- Modify: `lib/adapters/rest_api_adapter.py`
- Modify: `tests/test_rest_api_adapter.py`

- [ ] **Step 1: Add export and HTML stripping tests to `tests/test_rest_api_adapter.py`**

Append these test classes to the file:

```python
class TestRestApiHtmlStripping(unittest.TestCase):
    """Tests for HTML-to-text conversion matching export-posts.php behavior."""

    def setUp(self):
        self.adapter = RestApiAdapter(CONFIG)

    def test_strips_simple_tags(self):
        self.assertEqual(
            self.adapter._strip_html('<p>Hello <b>world</b></p>'),
            'Hello world',
        )

    def test_strips_nested_tags(self):
        self.assertEqual(
            self.adapter._strip_html('<div><p>Nested <em>content</em></p></div>'),
            'Nested content',
        )

    def test_strips_wp_block_comments(self):
        """WordPress block editor wraps content in <!-- wp:paragraph --> comments."""
        html = '<!-- wp:paragraph -->\n<p>Hello world</p>\n<!-- /wp:paragraph -->'
        result = self.adapter._strip_html(html)
        self.assertEqual(result, 'Hello world')

    def test_strips_shortcodes(self):
        html = '<p>Before [gallery ids="1,2,3"] after</p>'
        result = self.adapter._strip_html(html)
        self.assertNotIn('[gallery', result)
        self.assertIn('Before', result)
        self.assertIn('after', result)

    def test_collapses_whitespace(self):
        html = '<p>lots   of\n\nwhitespace\there</p>'
        result = self.adapter._strip_html(html)
        self.assertEqual(result, 'lots of whitespace here')

    def test_decodes_html_entities(self):
        html = '<p>AT&amp;T said &ldquo;hello&rdquo; &lt;3</p>'
        result = self.adapter._strip_html(html)
        self.assertIn('AT&T', result)
        self.assertIn('<3', result)
        self.assertIn('\u201c', result)  # left double quote

    def test_plain_text_passes_through(self):
        self.assertEqual(self.adapter._strip_html('no html here'), 'no html here')

    def test_self_closing_tags(self):
        html = 'line one<br/>line two<hr/>end'
        result = self.adapter._strip_html(html)
        self.assertIn('line one', result)
        self.assertIn('line two', result)


class TestRestApiExportPosts(unittest.TestCase):
    """Tests for export_posts() normalization and pagination."""

    @patch('urllib.request.urlopen')
    def test_normalizes_post_fields(self, mock_urlopen):
        """REST API nested objects (title.rendered, content.rendered) get flattened."""
        cats_response = _mock_response(
            [{'id': 3, 'name': 'Tech', 'slug': 'tech', 'description': '', 'count': 1, 'parent': 0}],
            headers={'X-WP-TotalPages': '1'},
        )
        posts_response = _mock_response(
            [{'id': 42, 'title': {'rendered': 'My Post'},
              'content': {'rendered': '<p>Hello world</p>'},
              'date': '2024-06-15T10:30:00', 'categories': [3],
              'link': 'https://example.com/my-post/'}],
            headers={'X-WP-TotalPages': '1'},
        )
        mock_urlopen.side_effect = [cats_response, posts_response]

        adapter = RestApiAdapter(CONFIG)
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            adapter.export_posts(path)
            with open(path) as f:
                posts = json.load(f)
            self.assertEqual(len(posts), 1)
            p = posts[0]
            self.assertEqual(p['post_id'], 42)
            self.assertEqual(p['title'], 'My Post')
            self.assertEqual(p['content'], 'Hello world')
            self.assertEqual(p['categories'], ['Tech'])
            self.assertEqual(p['category_slugs'], ['tech'])
            self.assertEqual(p['url'], 'https://example.com/my-post/')
            self.assertIn('2024', p['date'])
        finally:
            os.unlink(path)

    @patch('urllib.request.urlopen')
    def test_resolves_category_ids_to_names(self, mock_urlopen):
        """Posts have category IDs; export must include names and slugs."""
        cats_response = _mock_response(
            [{'id': 1, 'name': 'Music', 'slug': 'music', 'description': '', 'count': 5, 'parent': 0},
             {'id': 2, 'name': 'Jazz', 'slug': 'jazz', 'description': '', 'count': 3, 'parent': 1}],
            headers={'X-WP-TotalPages': '1'},
        )
        posts_response = _mock_response(
            [{'id': 10, 'title': {'rendered': 'Test'},
              'content': {'rendered': 'body'},
              'date': '2024-01-01T00:00:00', 'categories': [1, 2],
              'link': 'https://example.com/test/'}],
            headers={'X-WP-TotalPages': '1'},
        )
        mock_urlopen.side_effect = [cats_response, posts_response]

        adapter = RestApiAdapter(CONFIG)
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            adapter.export_posts(path)
            with open(path) as f:
                posts = json.load(f)
            self.assertEqual(sorted(posts[0]['categories']), ['Jazz', 'Music'])
            self.assertEqual(sorted(posts[0]['category_slugs']), ['jazz', 'music'])
        finally:
            os.unlink(path)

    @patch('urllib.request.urlopen')
    def test_unknown_category_id_skipped(self, mock_urlopen):
        """If a post references a category ID not in the lookup, skip it gracefully."""
        cats_response = _mock_response(
            [{'id': 1, 'name': 'Tech', 'slug': 'tech', 'description': '', 'count': 1, 'parent': 0}],
            headers={'X-WP-TotalPages': '1'},
        )
        posts_response = _mock_response(
            [{'id': 10, 'title': {'rendered': 'Test'},
              'content': {'rendered': 'body'},
              'date': '2024-01-01T00:00:00', 'categories': [1, 999],
              'link': 'https://example.com/test/'}],
            headers={'X-WP-TotalPages': '1'},
        )
        mock_urlopen.side_effect = [cats_response, posts_response]

        adapter = RestApiAdapter(CONFIG)
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            adapter.export_posts(path)
            with open(path) as f:
                posts = json.load(f)
            # Only the known category should appear
            self.assertEqual(posts[0]['categories'], ['Tech'])
            self.assertEqual(posts[0]['category_slugs'], ['tech'])
        finally:
            os.unlink(path)

    @patch('urllib.request.urlopen')
    def test_paginates_posts(self, mock_urlopen):
        cats_response = _mock_response([], headers={'X-WP-TotalPages': '0'})
        page1 = _mock_response(
            [{'id': 1, 'title': {'rendered': 'A'}, 'content': {'rendered': 'a'},
              'date': '2024-01-01T00:00:00', 'categories': [], 'link': 'https://example.com/a/'}],
            headers={'X-WP-TotalPages': '2'},
        )
        page2 = _mock_response(
            [{'id': 2, 'title': {'rendered': 'B'}, 'content': {'rendered': 'b'},
              'date': '2024-01-02T00:00:00', 'categories': [], 'link': 'https://example.com/b/'}],
            headers={'X-WP-TotalPages': '2'},
        )
        mock_urlopen.side_effect = [cats_response, page1, page2]

        adapter = RestApiAdapter(CONFIG)
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            adapter.export_posts(path)
            with open(path) as f:
                posts = json.load(f)
            self.assertEqual(len(posts), 2)
        finally:
            os.unlink(path)

    @patch('urllib.request.urlopen')
    def test_title_html_entities_decoded(self, mock_urlopen):
        """Titles with HTML entities like &#8217; (curly apostrophe) must be decoded."""
        cats_response = _mock_response([], headers={'X-WP-TotalPages': '0'})
        posts_response = _mock_response(
            [{'id': 1, 'title': {'rendered': 'It&#8217;s a test &amp; more'},
              'content': {'rendered': 'body'},
              'date': '2024-01-01T00:00:00', 'categories': [],
              'link': 'https://example.com/test/'}],
            headers={'X-WP-TotalPages': '1'},
        )
        mock_urlopen.side_effect = [cats_response, posts_response]

        adapter = RestApiAdapter(CONFIG)
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            adapter.export_posts(path)
            with open(path) as f:
                posts = json.load(f)
            self.assertIn('\u2019', posts[0]['title'])  # curly apostrophe
            self.assertIn('& more', posts[0]['title'])
        finally:
            os.unlink(path)
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
python3 -m unittest tests.test_rest_api_adapter.TestRestApiHtmlStripping tests.test_rest_api_adapter.TestRestApiExportPosts -v 2>&1 | head -5
```

Expected: `AttributeError: 'RestApiAdapter' object has no attribute '_strip_html'`

- [ ] **Step 3: Add `_strip_html()` and `export_posts()` to `rest_api_adapter.py`**

Add these imports at the top of the file:

```python
import html
import re
```

Add these methods to the `RestApiAdapter` class:

```python
    def _strip_html(self, text):
        """Strip HTML tags, block comments, shortcodes, and collapse whitespace.

        Replicates the behavior of export-posts.php:
        wp_strip_all_tags() + preg_replace('/\\s+/', ' ', ...) + html_entity_decode()
        """
        # Remove WordPress block editor comments: <!-- wp:anything -->
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        # Remove shortcodes: [gallery ids="1,2,3"]
        text = re.sub(r'\[/?[^\]]+\]', '', text)
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Decode HTML entities
        text = html.unescape(text)
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def export_posts(self, output_path):
        """Export all published posts to a JSON file."""
        # Build category ID -> name/slug lookup
        categories = self.list_categories()
        id_to_name = {c['term_id']: c['name'] for c in categories}
        id_to_slug = {c['term_id']: c['slug'] for c in categories}

        posts = []
        page = 1
        while True:
            data, resp = self._get_json(
                f'/wp/v2/posts?per_page=100&page={page}&status=publish'
                f'&_fields=id,title,content,date,categories,link'
            )
            for p in data:
                cat_ids = p.get('categories', [])
                cat_names = [id_to_name[cid] for cid in cat_ids if cid in id_to_name]
                cat_slugs = [id_to_slug[cid] for cid in cat_ids if cid in id_to_name]
                posts.append({
                    'post_id': p['id'],
                    'title': html.unescape(p['title']['rendered']),
                    'date': p['date'],
                    'content': self._strip_html(p['content']['rendered']),
                    'categories': cat_names,
                    'category_slugs': cat_slugs,
                    'url': p['link'],
                })
            total_pages = int(resp.getheader('X-WP-TotalPages', '1'))
            if page >= total_pages:
                break
            page += 1

        with open(output_path, 'w') as f:
            json.dump(posts, f)
        return output_path
```

- [ ] **Step 4: Run all REST adapter tests**

```bash
python3 -m unittest tests.test_rest_api_adapter -v
```

Expected: All tests PASS.

- [ ] **Step 5: Run all tests**

```bash
python3 -m unittest discover tests -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add lib/adapters/rest_api_adapter.py tests/test_rest_api_adapter.py
git commit -m "Add export_posts() with HTML stripping to REST API adapter"
```

---

## Task 4: WordPress.com API Adapter — HTTP Layer and Category Operations

**Files:**
- Create: `lib/adapters/wpcom_adapter.py`
- Create: `tests/test_wpcom_adapter.py`

- [ ] **Step 1: Write `tests/test_wpcom_adapter.py` with tests for `_request()`, `list_categories()`, category mutations, slug resolution, and error handling**

```python
"""Tests for the WordPress.com API adapter."""

import io
import json
import os
import sys
import unittest
import urllib.parse
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from adapters.wpcom_adapter import WpcomAdapter


def _mock_response(body, status=200):
    """Create a mock HTTP response."""
    data = json.dumps(body).encode() if not isinstance(body, bytes) else body
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = data
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


CONFIG = {
    'connection': {
        'method': 'wpcom-api',
        'site_id': '12345678',
        'access_token': 'test-bearer-token',
    }
}


class TestWpcomAuth(unittest.TestCase):
    """Tests that requests carry correct Bearer auth headers."""

    @patch('urllib.request.urlopen')
    def test_bearer_auth_header(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({'categories': []})
        adapter = WpcomAdapter(CONFIG)
        adapter.list_categories()

        req = mock_urlopen.call_args[0][0]
        auth = req.get_header('Authorization')
        self.assertEqual(auth, 'Bearer test-bearer-token')

    @patch('urllib.request.urlopen')
    def test_uses_correct_base_url(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({'categories': []})
        adapter = WpcomAdapter(CONFIG)
        adapter.list_categories()

        req = mock_urlopen.call_args[0][0]
        self.assertTrue(req.full_url.startswith(
            'https://public-api.wordpress.com/rest/v1.1/sites/12345678/'
        ))


class TestWpcomListCategories(unittest.TestCase):
    """Tests for list_categories() normalization."""

    @patch('urllib.request.urlopen')
    def test_normalizes_id_to_term_id(self, mock_urlopen):
        """WP.com returns 'ID'; adapter must emit 'term_id'."""
        mock_urlopen.return_value = _mock_response({'categories': [
            {'ID': 5, 'name': 'Tech', 'slug': 'tech',
             'description': 'Technology posts', 'post_count': 42, 'parent': 0},
        ]})
        adapter = WpcomAdapter(CONFIG)
        cats = adapter.list_categories()

        self.assertEqual(cats[0]['term_id'], 5)
        self.assertNotIn('ID', cats[0])
        self.assertEqual(cats[0]['name'], 'Tech')
        self.assertEqual(cats[0]['count'], 42)

    @patch('urllib.request.urlopen')
    def test_empty_site(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({'categories': []})
        adapter = WpcomAdapter(CONFIG)
        self.assertEqual(adapter.list_categories(), [])


class TestWpcomCategoryMutations(unittest.TestCase):
    """Tests for create, update, delete, and slug resolution."""

    @patch('urllib.request.urlopen')
    def test_create_category_returns_term_id(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({'ID': 77, 'name': 'New Cat', 'slug': 'new-cat'})
        adapter = WpcomAdapter(CONFIG)
        term_id = adapter.create_category('New Cat', 'new-cat', 'A new category')

        self.assertEqual(term_id, 77)
        req = mock_urlopen.call_args[0][0]
        self.assertIn('/categories/new', req.full_url)
        body = urllib.parse.parse_qs(req.data.decode())
        self.assertEqual(body['name'], ['New Cat'])

    @patch('urllib.request.urlopen')
    def test_update_category_resolves_slug(self, mock_urlopen):
        """update_category takes a term_id but WP.com needs the slug in the URL."""
        # First call: list_categories to resolve slug
        mock_urlopen.side_effect = [
            _mock_response({'categories': [
                {'ID': 5, 'name': 'Tech', 'slug': 'tech', 'description': '',
                 'post_count': 10, 'parent': 0},
            ]}),
            # Second call: the actual update
            _mock_response({'ID': 5}),
        ]
        adapter = WpcomAdapter(CONFIG)
        adapter.update_category(5, {'description': 'Updated'})

        req = mock_urlopen.call_args[0][0]
        self.assertIn('/categories/slug:tech', req.full_url)

    @patch('urllib.request.urlopen')
    def test_delete_category_resolves_slug(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _mock_response({'categories': [
                {'ID': 5, 'name': 'Tech', 'slug': 'tech', 'description': '',
                 'post_count': 10, 'parent': 0},
            ]}),
            _mock_response({'ID': 5}),
        ]
        adapter = WpcomAdapter(CONFIG)
        adapter.delete_category(5)

        req = mock_urlopen.call_args[0][0]
        self.assertIn('/categories/slug:tech/delete', req.full_url)

    @patch('urllib.request.urlopen')
    def test_slug_resolution_unknown_id_raises(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({'categories': []})
        adapter = WpcomAdapter(CONFIG)
        with self.assertRaises(ValueError) as ctx:
            adapter.update_category(999, {'description': 'nope'})
        self.assertIn('999', str(ctx.exception))

    @patch('urllib.request.urlopen')
    def test_get_default_category(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({
            'settings': {'default_category': 7}
        })
        adapter = WpcomAdapter(CONFIG)
        self.assertEqual(adapter.get_default_category(), 7)

    @patch('urllib.request.urlopen')
    def test_set_post_categories(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({'ID': 123})
        adapter = WpcomAdapter(CONFIG)
        adapter.set_post_categories(123, [1, 5, 9])

        req = mock_urlopen.call_args[0][0]
        body = urllib.parse.parse_qs(req.data.decode())
        self.assertEqual(body['categories'], ['1,5,9'])


class TestWpcomErrorHandling(unittest.TestCase):
    """Tests for HTTP error responses."""

    @patch('urllib.request.urlopen')
    def test_401_includes_status_in_message(self, mock_urlopen):
        from urllib.error import HTTPError
        error_body = json.dumps({'error': 'invalid_token', 'message': 'Token expired'}).encode()
        mock_urlopen.side_effect = HTTPError(
            'https://public-api.wordpress.com/rest/v1.1/sites/123/categories',
            401, 'Unauthorized', {}, io.BytesIO(error_body))
        adapter = WpcomAdapter(CONFIG)

        with self.assertRaises(Exception) as ctx:
            adapter.list_categories()
        self.assertIn('401', str(ctx.exception))

    @patch('urllib.request.urlopen')
    def test_html_error_page_doesnt_crash(self, mock_urlopen):
        from urllib.error import HTTPError
        html_body = b'<html><body>503 Service Unavailable</body></html>'
        mock_urlopen.side_effect = HTTPError(
            'https://public-api.wordpress.com/rest/v1.1/sites/123/categories',
            503, 'Service Unavailable', {}, io.BytesIO(html_body))
        adapter = WpcomAdapter(CONFIG)

        with self.assertRaises(Exception) as ctx:
            adapter.list_categories()
        self.assertIn('503', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m unittest tests.test_wpcom_adapter -v 2>&1 | head -5
```

Expected: `ModuleNotFoundError: No module named 'adapters.wpcom_adapter'`

- [ ] **Step 3: Implement `lib/adapters/wpcom_adapter.py` — HTTP layer and category operations**

```python
"""WordPress.com / Jetpack REST API adapter."""

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request


WPCOM_BASE = 'https://public-api.wordpress.com/rest/v1.1'


class WpcomAdapter:
    """
    Adapter for the WordPress.com REST API.
    Works for WordPress.com hosted sites and self-hosted sites with Jetpack.
    """

    def __init__(self, config):
        self.config = config
        conn = config['connection']
        self.site_id = conn['site_id']
        self._auth = f"Bearer {conn['access_token']}"
        self._base_url = f'{WPCOM_BASE}/sites/{self.site_id}'

    def _request(self, method, path, data=None):
        """Make an authenticated request to the WordPress.com API."""
        url = f'{self._base_url}{path}'
        body = urllib.parse.urlencode(data).encode() if data else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header('Authorization', self._auth)
        if body is not None:
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')

        try:
            resp = urllib.request.urlopen(req)
            return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode(errors='replace')
            raise Exception(
                f'WP.com API error {e.code} {method} {path}: {error_body}'
            ) from None

    def _resolve_slug(self, term_id):
        """Resolve a term ID to its slug via the categories endpoint."""
        categories = self.list_categories()
        for cat in categories:
            if cat['term_id'] == term_id:
                return cat['slug']
        raise ValueError(
            f'Category with term_id {term_id} not found'
        )

    def list_categories(self):
        """List all categories."""
        data = self._request('GET', '/categories?number=1000')
        categories = []
        for cat in data.get('categories', []):
            categories.append({
                'term_id': cat['ID'],
                'name': cat['name'],
                'slug': cat['slug'],
                'description': cat.get('description', ''),
                'count': cat.get('post_count', 0),
                'parent': cat.get('parent', 0),
            })
        return categories

    def create_category(self, name, slug, description=''):
        """Create a new category. Returns the new term ID."""
        data = self._request('POST', '/categories/new', {
            'name': name, 'slug': slug, 'description': description,
        })
        return data['ID']

    def update_category(self, term_id, fields):
        """Update a category. Resolves term_id to slug for the WP.com URL."""
        slug = self._resolve_slug(term_id)
        self._request('POST', f'/categories/slug:{slug}', fields)

    def delete_category(self, term_id):
        """Delete a category. Resolves term_id to slug for the WP.com URL."""
        slug = self._resolve_slug(term_id)
        self._request('POST', f'/categories/slug:{slug}/delete')

    def set_post_categories(self, post_id, category_ids):
        """Set categories for a post. WP.com accepts comma-separated IDs."""
        ids_str = ','.join(str(cid) for cid in category_ids)
        self._request('POST', f'/posts/{post_id}', {'categories': ids_str})

    def get_default_category(self):
        """Get the term ID of the site's default category."""
        data = self._request('GET', '/settings')
        return data['settings']['default_category']
```

- [ ] **Step 4: Run all WP.com adapter tests**

```bash
python3 -m unittest tests.test_wpcom_adapter -v
```

Expected: All tests PASS.

- [ ] **Step 5: Run the factory test for wpcom-api**

```bash
python3 -m unittest tests.test_factory.TestCreateAdapter.test_wpcom_api -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add lib/adapters/wpcom_adapter.py tests/test_wpcom_adapter.py
git commit -m "Add WordPress.com API adapter with category operations and tests"
```

---

## Task 5: WordPress.com Adapter — `export_posts()` with WP.com Pagination

**Files:**
- Modify: `lib/adapters/wpcom_adapter.py`
- Modify: `tests/test_wpcom_adapter.py`

- [ ] **Step 1: Add export tests to `tests/test_wpcom_adapter.py`**

Append these test classes to the file:

```python
class TestWpcomExportPosts(unittest.TestCase):
    """Tests for export_posts() with WP.com-specific response shapes."""

    @patch('urllib.request.urlopen')
    def test_converts_category_hash_to_lists(self, mock_urlopen):
        """WP.com returns categories as a name-keyed hash, not an array."""
        cats_response = _mock_response({'categories': [
            {'ID': 3, 'name': 'Tech', 'slug': 'tech', 'description': '', 'post_count': 1, 'parent': 0},
        ]})
        posts_response = _mock_response({
            'posts': [{
                'ID': 42, 'title': 'My Post',
                'content': '<p>Hello world</p>',
                'date': '2024-06-15T10:30:00+00:00',
                'categories': {
                    'Tech': {'ID': 3, 'name': 'Tech', 'slug': 'tech'},
                },
                'URL': 'https://example.wordpress.com/my-post/',
            }],
            'meta': {},
        })
        mock_urlopen.side_effect = [cats_response, posts_response]

        adapter = WpcomAdapter(CONFIG)
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            adapter.export_posts(path)
            with open(path) as f:
                posts = json.load(f)
            self.assertEqual(len(posts), 1)
            p = posts[0]
            self.assertEqual(p['post_id'], 42)
            self.assertEqual(p['title'], 'My Post')
            self.assertEqual(p['content'], 'Hello world')
            self.assertEqual(p['categories'], ['Tech'])
            self.assertEqual(p['category_slugs'], ['tech'])
            self.assertEqual(p['url'], 'https://example.wordpress.com/my-post/')
        finally:
            os.unlink(path)

    @patch('urllib.request.urlopen')
    def test_page_handle_pagination(self, mock_urlopen):
        """WP.com uses meta.next_page for cursor-based pagination."""
        cats_response = _mock_response({'categories': []})
        page1 = _mock_response({
            'posts': [{
                'ID': 1, 'title': 'A', 'content': 'a',
                'date': '2024-01-01T00:00:00+00:00',
                'categories': {}, 'URL': 'https://example.com/a/',
            }],
            'meta': {'next_page': 'cursor_token_abc'},
        })
        page2 = _mock_response({
            'posts': [{
                'ID': 2, 'title': 'B', 'content': 'b',
                'date': '2024-01-02T00:00:00+00:00',
                'categories': {}, 'URL': 'https://example.com/b/',
            }],
            'meta': {},
        })
        mock_urlopen.side_effect = [cats_response, page1, page2]

        adapter = WpcomAdapter(CONFIG)
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            adapter.export_posts(path)
            with open(path) as f:
                posts = json.load(f)
            self.assertEqual(len(posts), 2)

            # Verify second request used page_handle
            second_posts_req = mock_urlopen.call_args_list[2][0][0]
            self.assertIn('page_handle=cursor_token_abc', second_posts_req.full_url)
        finally:
            os.unlink(path)

    @patch('urllib.request.urlopen')
    def test_multiple_categories_on_post(self, mock_urlopen):
        """Posts can have multiple categories in the hash."""
        cats_response = _mock_response({'categories': []})
        posts_response = _mock_response({
            'posts': [{
                'ID': 1, 'title': 'Test', 'content': 'body',
                'date': '2024-01-01T00:00:00+00:00',
                'categories': {
                    'Tech': {'ID': 3, 'name': 'Tech', 'slug': 'tech'},
                    'AI': {'ID': 7, 'name': 'AI', 'slug': 'ai'},
                },
                'URL': 'https://example.com/test/',
            }],
            'meta': {},
        })
        mock_urlopen.side_effect = [cats_response, posts_response]

        adapter = WpcomAdapter(CONFIG)
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            adapter.export_posts(path)
            with open(path) as f:
                posts = json.load(f)
            self.assertEqual(sorted(posts[0]['categories']), ['AI', 'Tech'])
            self.assertEqual(sorted(posts[0]['category_slugs']), ['ai', 'tech'])
        finally:
            os.unlink(path)

    @patch('urllib.request.urlopen')
    def test_empty_site(self, mock_urlopen):
        cats_response = _mock_response({'categories': []})
        posts_response = _mock_response({'posts': [], 'meta': {}})
        mock_urlopen.side_effect = [cats_response, posts_response]

        adapter = WpcomAdapter(CONFIG)
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            adapter.export_posts(path)
            with open(path) as f:
                posts = json.load(f)
            self.assertEqual(posts, [])
        finally:
            os.unlink(path)

    @patch('urllib.request.urlopen')
    def test_html_stripped_from_content(self, mock_urlopen):
        cats_response = _mock_response({'categories': []})
        posts_response = _mock_response({
            'posts': [{
                'ID': 1, 'title': 'Test',
                'content': '<!-- wp:paragraph -->\n<p>Hello <b>world</b></p>\n<!-- /wp:paragraph -->',
                'date': '2024-01-01T00:00:00+00:00',
                'categories': {}, 'URL': 'https://example.com/test/',
            }],
            'meta': {},
        })
        mock_urlopen.side_effect = [cats_response, posts_response]

        adapter = WpcomAdapter(CONFIG)
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            adapter.export_posts(path)
            with open(path) as f:
                posts = json.load(f)
            self.assertEqual(posts[0]['content'], 'Hello world')
        finally:
            os.unlink(path)
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
python3 -m unittest tests.test_wpcom_adapter.TestWpcomExportPosts -v 2>&1 | head -5
```

Expected: `AttributeError: 'WpcomAdapter' object has no attribute 'export_posts'`

- [ ] **Step 3: Add `_strip_html()` and `export_posts()` to `wpcom_adapter.py`**

Add these methods to the `WpcomAdapter` class:

```python
    def _strip_html(self, text):
        """Strip HTML tags, block comments, shortcodes, and collapse whitespace."""
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        text = re.sub(r'\[/?[^\]]+\]', '', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = html.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def export_posts(self, output_path):
        """Export all published posts to a JSON file."""
        posts = []
        page_handle = None
        while True:
            params = 'number=100&status=publish&fields=ID,title,content,date,categories,URL'
            if page_handle:
                params += f'&page_handle={urllib.parse.quote(page_handle, safe="")}'
            data = self._request('GET', f'/posts?{params}')

            for p in data.get('posts', []):
                # Categories are a hash keyed by name
                cat_hash = p.get('categories', {})
                cat_names = list(cat_hash.keys())
                cat_slugs = [cat_hash[name]['slug'] for name in cat_names]

                posts.append({
                    'post_id': p['ID'],
                    'title': html.unescape(p.get('title', '')),
                    'date': p.get('date', ''),
                    'content': self._strip_html(p.get('content', '')),
                    'categories': cat_names,
                    'category_slugs': cat_slugs,
                    'url': p.get('URL', ''),
                })

            page_handle = data.get('meta', {}).get('next_page')
            if not page_handle:
                break

        with open(output_path, 'w') as f:
            json.dump(posts, f)
        return output_path
```

- [ ] **Step 4: Run all WP.com adapter tests**

```bash
python3 -m unittest tests.test_wpcom_adapter -v
```

Expected: All tests PASS.

- [ ] **Step 5: Run all tests**

```bash
python3 -m unittest discover tests -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add lib/adapters/wpcom_adapter.py tests/test_wpcom_adapter.py
git commit -m "Add export_posts() with page_handle pagination to WP.com adapter"
```

---

## Task 6: Update Agent Files and Documentation

**Files:**
- Modify: `agents/export.md`
- Modify: `agents/apply.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Add adapter usage to `agents/export.md`**

Add this section after the existing "## Setup" section (before "## What to Export"):

```markdown
### Using the Adapter

The preferred approach for all connection methods:

```python
import json
from lib.adapters import create_adapter

config = json.load(open('config.json'))
adapter = create_adapter(config)

# Export categories
cats = adapter.list_categories()
with open('data/export/categories.json', 'w') as f:
    json.dump(cats, f, indent=2)

# Export posts
adapter.export_posts('data/export/posts.json')
```

This works for WP-CLI, REST API, and WordPress.com connections. The adapter handles pagination, HTML stripping, and field normalization internally.

The method-specific instructions below are kept as fallback documentation.
```

- [ ] **Step 2: Add adapter usage to `agents/apply.md`**

Add this section after the existing "## Setup" section (before "## Logging"):

```markdown
### Using the Adapter

For individual operations, the preferred approach for all connection methods:

```python
import json
from lib.adapters import create_adapter

config = json.load(open('config.json'))
adapter = create_adapter(config)

# Category operations
adapter.create_category('New Cat', 'new-cat', 'Description here')
adapter.update_category(term_id, {'description': 'Updated description'})
adapter.set_post_categories(post_id, [cat_id_1, cat_id_2])
adapter.delete_category(term_id)
default_cat = adapter.get_default_category()
```

For **bulk post category changes** via WP-CLI, continue using `lib/apply-changes.php` — it handles paginated processing, logging, and dry-run mode that the adapter doesn't replicate.

The method-specific curl examples below are kept as fallback documentation.
```

- [ ] **Step 3: Update the adapter layer section in `AGENTS.md`**

Find the "## WordPress Access Adapters" section in `AGENTS.md` and replace it with:

```markdown
## WordPress Access Adapters

The adapter layer (`lib/adapters/`) provides a uniform Python interface regardless of connection method. Use the factory function to get the right adapter:

```python
from lib.adapters import create_adapter
import json

config = json.load(open('config.json'))
adapter = create_adapter(config)
```

Implemented adapters:

| Adapter | Connection Methods | Notes |
|---------|-------------------|-------|
| `WpCliAdapter` | `wp-cli-ssh`, `wp-cli-local` | Uses subprocess + PHP scripts |
| `RestApiAdapter` | `rest-api` | WordPress REST API + Application Passwords |
| `WpcomAdapter` | `wpcom-api` | WordPress.com / Jetpack REST API |

Required operations:
- `list_categories()` — Get all categories with counts and descriptions
- `export_posts(output_path)` — Export all posts with content, categories, and slugs to JSON
- `set_post_categories(id, category_ids)` — Set categories for a post
- `create_category(name, slug, description)` — Create a new category
- `update_category(id, fields)` — Update category name/slug/description
- `delete_category(id)` — Delete a category
- `get_default_category()` — Get the default category term ID
```

- [ ] **Step 4: Verify no broken markdown**

```bash
python3 -c "
import re
for f in ['agents/export.md', 'agents/apply.md', 'AGENTS.md']:
    with open(f) as fh:
        content = fh.read()
    # Check for unclosed code blocks
    count = content.count('\`\`\`')
    if count % 2 != 0:
        print(f'WARNING: {f} has {count} code fences (odd number)')
    else:
        print(f'{f}: OK ({count} code fences)')
"
```

Expected: All files OK.

- [ ] **Step 5: Run all tests one final time to ensure nothing is broken**

```bash
python3 -m unittest discover tests -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add agents/export.md agents/apply.md AGENTS.md
git commit -m "Update agent files and docs to reference adapter factory"
```
