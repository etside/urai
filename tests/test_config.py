"""Config defaults + env overrides (AUTH_GET prod default, stream, cache)."""
import os
import unittest

from jev import config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in (
            "URAI_ENV", "URAI_PROD", "URAI_AUTH_GET", "URAI_STREAM",
            "CACHE_ENABLED", "CACHE_MAX", "CACHE_SIMILARITY")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        config.reload()

    def test_dev_defaults(self):
        c = config.reload()
        self.assertFalse(c.prod)
        self.assertFalse(c.AUTH_GET)  # off outside prod
        self.assertTrue(c.STREAM)
        self.assertTrue(c.CACHE_ENABLED)

    def test_prod_enables_auth_get_by_default(self):
        os.environ["URAI_ENV"] = "prod"
        self.assertTrue(config.reload().AUTH_GET)

    def test_explicit_flag_overrides_prod_default(self):
        os.environ["URAI_ENV"] = "production"
        os.environ["URAI_AUTH_GET"] = "0"
        self.assertFalse(config.reload().AUTH_GET)

    def test_numeric_clamps(self):
        os.environ["CACHE_SIMILARITY"] = "5"
        os.environ["CACHE_MAX"] = "0"
        c = config.reload()
        self.assertEqual(c.CACHE_SIMILARITY, 1.0)
        self.assertGreaterEqual(c.CACHE_MAX, 1)

    def test_as_dict_shape(self):
        d = config.reload().as_dict()
        for k in ("prod", "auth_get", "stream", "cache_enabled"):
            self.assertIn(k, d)


if __name__ == "__main__":
    unittest.main()
