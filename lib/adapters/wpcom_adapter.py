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

    def create_category(self, name, slug, description='', parent=0):
        """Create a new category. Returns the new term ID."""
        data = self._request('POST', '/categories/new', {
            'name': name, 'slug': slug, 'description': description,
            'parent': parent,
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
        self.list_categories()
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
