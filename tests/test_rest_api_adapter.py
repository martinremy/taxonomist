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
