"""WordPress REST API adapter using Application Passwords."""

import base64
import html
import json
import re
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
