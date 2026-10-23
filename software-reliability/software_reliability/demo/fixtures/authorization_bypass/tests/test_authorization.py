import unittest

from service import Handler, ServeConfig, Service, authorize


class AuthorizationTests(unittest.TestCase):
    def test_top_level_path_requires_admin(self):
        config = ServeConfig(web_handlers=(Handler(path="/srv/public"),))
        self.assertFalse(authorize(config, is_admin=False))

    def test_configuration_without_paths_is_allowed(self):
        self.assertTrue(authorize(ServeConfig(), is_admin=False))

    def test_service_path_requires_admin(self):
        config = ServeConfig(
            services=(Service(handlers=(Handler(path="/srv/private"),)),)
        )
        self.assertFalse(authorize(config, is_admin=False))


if __name__ == "__main__":
    unittest.main()
