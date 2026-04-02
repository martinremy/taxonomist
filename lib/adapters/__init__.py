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
