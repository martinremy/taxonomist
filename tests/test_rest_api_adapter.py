"""Tests for the WordPress REST API adapter."""

import base64
import io
import json
import os
import sys
import unittest
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
    def test_preserves_parent_child_hierarchy(self, mock_urlopen):
        """Parent category IDs must survive normalization."""
        api_cats = [
            {'id': 10, 'name': 'Music', 'slug': 'music', 'description': '', 'count': 5, 'parent': 0},
            {'id': 11, 'name': 'Jazz', 'slug': 'jazz', 'description': '', 'count': 3, 'parent': 10},
        ]
        mock_urlopen.return_value = _mock_response(api_cats,
                                                   headers={'X-WP-TotalPages': '1'})
        adapter = RestApiAdapter(CONFIG)
        cats = adapter.list_categories()

        self.assertEqual(cats[0]['parent'], 0)
        self.assertEqual(cats[1]['parent'], 10)

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
        self.assertEqual(body['parent'], 0)

    @patch('urllib.request.urlopen')
    def test_create_child_category_sends_parent(self, mock_urlopen):
        """Creating a child category must send the parent ID."""
        mock_urlopen.return_value = _mock_response({'id': 100, 'name': 'Jazz', 'slug': 'jazz'})
        adapter = RestApiAdapter(CONFIG)
        term_id = adapter.create_category('Jazz', 'jazz', 'Jazz music', parent=10)

        self.assertEqual(term_id, 100)
        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        self.assertEqual(body['parent'], 10)

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


if __name__ == '__main__':
    unittest.main()
