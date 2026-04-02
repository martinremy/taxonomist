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
    def test_preserves_parent_child_hierarchy(self, mock_urlopen):
        """Parent category IDs must survive normalization."""
        mock_urlopen.return_value = _mock_response({'categories': [
            {'ID': 10, 'name': 'Music', 'slug': 'music',
             'description': '', 'post_count': 5, 'parent': 0},
            {'ID': 11, 'name': 'Jazz', 'slug': 'jazz',
             'description': '', 'post_count': 3, 'parent': 10},
        ]})
        adapter = WpcomAdapter(CONFIG)
        cats = adapter.list_categories()

        self.assertEqual(cats[0]['parent'], 0)
        self.assertEqual(cats[1]['parent'], 10)

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
        self.assertEqual(body['parent'], ['0'])

    @patch('urllib.request.urlopen')
    def test_create_child_category_sends_parent(self, mock_urlopen):
        """Creating a child category must send the parent ID."""
        mock_urlopen.return_value = _mock_response({'ID': 78, 'name': 'Jazz', 'slug': 'jazz'})
        adapter = WpcomAdapter(CONFIG)
        term_id = adapter.create_category('Jazz', 'jazz', 'Jazz music', parent=10)

        self.assertEqual(term_id, 78)
        req = mock_urlopen.call_args[0][0]
        body = urllib.parse.parse_qs(req.data.decode())
        self.assertEqual(body['parent'], ['10'])

    @patch('urllib.request.urlopen')
    def test_update_category_resolves_slug(self, mock_urlopen):
        """update_category takes a term_id but WP.com needs the slug in the URL."""
        mock_urlopen.side_effect = [
            _mock_response({'categories': [
                {'ID': 5, 'name': 'Tech', 'slug': 'tech', 'description': '',
                 'post_count': 10, 'parent': 0},
            ]}),
            _mock_response({'ID': 5}),
        ]
        adapter = WpcomAdapter(CONFIG)
        adapter.update_category(5, {'description': 'Updated'})

        req = mock_urlopen.call_args[0][0]
        self.assertIn('/categories/slug:tech', req.full_url)

    @patch('urllib.request.urlopen')
    def test_update_category_reparents(self, mock_urlopen):
        """Reparenting a category via update must send the parent ID."""
        mock_urlopen.side_effect = [
            _mock_response({'categories': [
                {'ID': 11, 'name': 'Jazz', 'slug': 'jazz', 'description': '',
                 'post_count': 3, 'parent': 0},
            ]}),
            _mock_response({'ID': 11}),
        ]
        adapter = WpcomAdapter(CONFIG)
        adapter.update_category(11, {'parent': 10})

        req = mock_urlopen.call_args[0][0]
        body = urllib.parse.parse_qs(req.data.decode())
        self.assertEqual(body['parent'], ['10'])

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


if __name__ == '__main__':
    unittest.main()
