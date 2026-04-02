# REST API & WordPress.com API Adapters

## Problem

Taxonomist has a fully implemented WP-CLI adapter (`lib/adapters/wp_cli_adapter.py`) but the REST API and WordPress.com API connection methods have no adapter classes. The agent improvises API calls from curl examples in the agent markdown files each session. This is fragile and unrepeatable.

## Scope

Build two new adapter classes:

- `RestApiAdapter` — WordPress REST API with Application Passwords (self-hosted WordPress 5.6+)
- `WpcomAdapter` — WordPress.com / Jetpack REST API (WordPress.com hosted or Jetpack-connected)

Plus a factory function and two small additions to the existing `WpCliAdapter`.

JWT and XML-RPC are out of scope (niche, low value).

## Decision: No Base Class

These adapters are write-once-and-stable. An abstract base class would add indirection without ongoing value. Instead, each adapter is a standalone class that implements the same method signatures by convention. A factory function routes config to the right class.

## File Layout

```
lib/adapters/
  __init__.py            # NEW  — create_adapter() factory
  wp_cli_adapter.py      # EXISTING — add update_category(), get_default_category()
  rest_api_adapter.py    # NEW
  wpcom_adapter.py       # NEW

tests/
  test_rest_api_adapter.py   # NEW
  test_wpcom_adapter.py      # NEW
```

## Factory Function (`lib/adapters/__init__.py`)

```python
def create_adapter(config):
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

## Common Interface

Both new adapters implement these methods, returning the same data shapes as `WpCliAdapter`:

| Method | Input | Output |
|--------|-------|--------|
| `list_categories()` | -- | `[{"term_id": int, "name": str, "slug": str, "description": str, "count": int, "parent": int}]` |
| `export_posts(output_path)` | path to write JSON | Writes file, returns path. Schema: `post_id`, `title`, `date`, `content` (HTML-stripped), `categories` (names), `category_slugs`, `url` |
| `set_post_categories(post_id, category_ids)` | post ID, list of term IDs | -- |
| `create_category(name, slug, description)` | -- | Returns created term ID |
| `update_category(term_id, fields)` | term ID, dict of fields | -- |
| `delete_category(term_id)` | term ID | -- |
| `get_default_category()` | -- | Returns term ID of default category |

`update_category()` and `get_default_category()` are new vs. the current `WpCliAdapter` and will be added there too for parity.

## REST API Adapter (`rest_api_adapter.py`)

### Auth

Basic auth: `Authorization: Basic base64(username:app_password)` on every request. Credentials from config.json.

### Config Shape

```json
{
  "site_url": "https://example.com",
  "connection": {
    "method": "rest-api",
    "api_url": "https://example.com/wp-json",
    "username": "admin",
    "app_password": "xxxx xxxx xxxx xxxx"
  }
}
```

### HTTP Layer

A private `_request(method, path, data=None)` helper using `urllib.request`:
- Builds full URL from `api_url` + path
- Injects Basic auth header
- Sends/receives JSON
- Raises `Exception` with status code and response body on HTTP errors

### Method Details

**`list_categories()`**
- `GET /wp/v2/categories?per_page=100&page=N`
- Paginate using `X-WP-TotalPages` response header
- Normalize: `id` -> `term_id`

**`export_posts(output_path)`**
- `GET /wp/v2/posts?per_page=100&page=N&status=publish&_fields=id,title,content,date,categories,link`
- REST API returns rendered HTML for `content.rendered` and `title.rendered` -> strip HTML tags, collapse whitespace
- REST API returns category IDs, not names -> build ID-to-name/slug lookup from `list_categories()` first
- Stream results: accumulate in memory per page, write complete JSON at the end (posts.json for a typical blog fits in memory; the PHP script's streaming approach was for server-side memory constraints that don't apply here)
- Output format matches `export-posts.php`: `post_id`, `title`, `date`, `content`, `categories` (names), `category_slugs`, `url`

**`set_post_categories(post_id, category_ids)`**
- `POST /wp/v2/posts/{id}` with `{"categories": [1, 2, 3]}`

**`create_category(name, slug, description)`**
- `POST /wp/v2/categories` with `{"name": "...", "slug": "...", "description": "..."}`
- Returns `response["id"]` as the new term ID

**`update_category(term_id, fields)`**
- `POST /wp/v2/categories/{id}` with the fields dict (e.g. `{"description": "new text"}`)

**`delete_category(term_id)`**
- `DELETE /wp/v2/categories/{id}?force=true`

**`get_default_category()`**
- `GET /wp/v2/settings` -> `response["default_category"]`

## WordPress.com API Adapter (`wpcom_adapter.py`)

### Auth

Bearer token: `Authorization: Bearer {access_token}` on every request. Token from config.json (obtained via `lib/wpcom-auth.py`).

### Config Shape

```json
{
  "site_url": "https://example.wordpress.com",
  "connection": {
    "method": "wpcom-api",
    "site_id": "12345678",
    "access_token": "THE_TOKEN"
  }
}
```

### HTTP Layer

A private `_request(method, path, data=None)` helper using `urllib.request`:
- Base URL: `https://public-api.wordpress.com/rest/v1.1/sites/{site_id}`
- Injects Bearer auth header
- Sends form-encoded data for POST (WP.com API convention), receives JSON
- Raises `Exception` with status code and response body on HTTP errors

### Method Details

**`list_categories()`**
- `GET /sites/{id}/categories?number=1000`
- Response is `{"categories": [...]}` wrapper -> unwrap
- Normalize: `ID` -> `term_id`, field names to match common interface

**`export_posts(output_path)`**
- `GET /sites/{id}/posts?number=100&status=publish&fields=ID,title,content,date,categories,URL`
- Paginate using `meta.next_page` as `page_handle` parameter on subsequent requests
- Categories come as a name-keyed hash: `{"Tech": {"ID": 5, "slug": "tech", ...}}` -> extract keys for names, map values for slugs
- Content is HTML -> strip tags, collapse whitespace (same as REST adapter)
- Output format matches the common schema

**`set_post_categories(post_id, category_ids)`**
- `POST /sites/{id}/posts/{post_id}` with form-encoded `categories` param
- WP.com accepts comma-separated category IDs: `categories=1,2,3`

**`create_category(name, slug, description)`**
- `POST /sites/{id}/categories/new` with form-encoded `name`, `slug`, `description`
- Returns `response["ID"]` as the new term ID

**`update_category(term_id, fields)`**
- WP.com uses slug-based URLs: `POST /sites/{id}/categories/slug:{slug}`
- Adapter resolves term_id to slug internally (from cached category list or a lookup call)
- Sends form-encoded fields

**`delete_category(term_id)`**
- `POST /sites/{id}/categories/slug:{slug}/delete`
- Same slug resolution as update

**`get_default_category()`**
- `GET /sites/{id}/settings` -> `response["settings"]["default_category"]`

## Changes to Existing Code

### `WpCliAdapter`

Add two methods for interface parity:

- `update_category(term_id, fields)` — `wp term update {term_id} category --name=... --description=...`
- `get_default_category()` — `wp option get default_category`, return as int

### Agent Files

Update `agents/export.md` and `agents/apply.md` to reference `create_adapter(config)` as the preferred path. Keep curl examples as fallback documentation.

### `AGENTS.md`

Update the adapter layer section to note that REST and WP.com adapters now exist.

## API Content Types

The two APIs expect different POST body formats:

- **REST API** (`rest_api_adapter.py`): JSON request bodies (`Content-Type: application/json`)
- **WordPress.com API** (`wpcom_adapter.py`): Form-encoded request bodies (`Content-Type: application/x-www-form-urlencoded`)

Each adapter's `_request()` helper handles this internally.

## Dependencies

None beyond the Python standard library. All HTTP via `urllib.request`. Matches the existing pattern (`wpcom-auth.py`, `wp_cli_adapter.py`).

## Error Handling

Both adapters raise `Exception` with a message including the HTTP status code and response body. No retry logic — the AI agent decides whether to retry. Matches `WpCliAdapter`'s pattern.

## Tests

### Approach

Unit tests using `unittest` and `unittest.mock.patch` on `urllib.request.urlopen`. No external dependencies, no real WordPress sites. Two test files following the style of the existing `tests/test_helpers.py`.

### What to Test

Tests focus on logic at the boundary where adapter code encounters real WordPress API responses — the normalization, pagination, and format conversion where bugs actually hide.

**Response normalization (both adapters):**
- REST API `id` field maps to `term_id` in category output
- WP.com `ID` field maps to `term_id` in category output
- WP.com category hash-keyed-by-name converts to names list and slugs list on posts
- REST API `title.rendered` / `content.rendered` nested objects get unwrapped correctly
- Missing or null fields in API responses don't crash (real sites have messy data)

**HTML stripping (both adapters):**
- Standard tags stripped, text preserved
- Nested tags, self-closing tags, HTML entities
- Content with no HTML passes through unchanged
- WordPress-specific patterns: `<!-- wp:paragraph -->` block editor comments, shortcodes like `[gallery]`

**Pagination (both adapters):**
- REST API: multi-page fetch driven by `X-WP-TotalPages` header, stops at last page
- WP.com: `page_handle` pagination follows `meta.next_page`, stops when absent
- Single-page response (no pagination needed)
- Empty site (zero posts, zero categories)

**Auth:**
- REST adapter sends correct Basic auth header format
- WP.com adapter sends correct Bearer header format

**WP.com slug resolution:**
- `update_category()` and `delete_category()` resolve term_id to slug correctly
- Error when term_id doesn't exist in category list

**Error handling:**
- HTTP 401 (expired token / bad password) produces a useful error message
- HTTP 404 (deleted post/category) produces a useful error message
- Non-JSON response body (e.g. HTML error page from a misconfigured server) doesn't crash the error handler

**Factory function:**
- Returns correct adapter class for each known method string
- Raises `ValueError` for unknown methods

### What NOT to Test

- That `urllib.request` works (stdlib)
- Auth header construction in isolation (tested implicitly by every request test)
- Simple field pass-through with no transformation
- Constructor stores config (no logic)
