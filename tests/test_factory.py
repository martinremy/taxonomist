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

    def test_unknown_method_raises(self):
        config = {'connection': {'method': 'carrier-pigeon'}}
        with self.assertRaises(ValueError) as ctx:
            create_adapter(config)
        self.assertIn('carrier-pigeon', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
