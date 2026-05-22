from __future__ import annotations

import importlib
import os
import unittest


class ProductionConfigTests(unittest.TestCase):
    ENV_KEYS = {
        "APP_ENV",
        "CONNECTOR_MODE",
        "LOCAL_AGENT_BOOTSTRAP_ENABLED",
        "ALLOW_DEV_AUTH",
        "GOOGLE_CLIENT_ID",
        "COOKIE_SECURE",
        "COOKIE_SAMESITE",
    }

    def setUp(self) -> None:
        self.original_env = {key: os.environ.get(key) for key in self.ENV_KEYS}

    def tearDown(self) -> None:
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import backend.config as config

        importlib.reload(config)

    def set_production_env(self, *, cookie_samesite: str) -> None:
        os.environ.update(
            {
                "APP_ENV": "production",
                "CONNECTOR_MODE": "polling",
                "LOCAL_AGENT_BOOTSTRAP_ENABLED": "false",
                "ALLOW_DEV_AUTH": "false",
                "GOOGLE_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
                "COOKIE_SECURE": "true",
                "COOKIE_SAMESITE": cookie_samesite,
            }
        )

    def test_production_requires_cross_origin_cookie_samesite_none(self) -> None:
        import backend.config as config

        self.set_production_env(cookie_samesite="lax")

        with self.assertRaisesRegex(RuntimeError, "COOKIE_SAMESITE=none"):
            importlib.reload(config)

    def test_production_accepts_cross_origin_cookie_settings(self) -> None:
        import backend.config as config

        self.set_production_env(cookie_samesite="none")

        reloaded = importlib.reload(config)

        self.assertTrue(reloaded.COOKIE_SECURE)
        self.assertEqual(reloaded.COOKIE_SAMESITE, "none")


if __name__ == "__main__":
    unittest.main()
