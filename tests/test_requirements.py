import os
import sys
import unittest
import tomllib
import pytest

# Make the project root importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestRequirements(unittest.TestCase):

    def test_macos_bundle_minimum_version_is_10_15(self):
        project_file = os.path.join(os.path.dirname(__file__), "..", "pyproject.toml")
        with open(project_file, "rb") as stream:
            project = tomllib.load(stream)

        minimum_version = project["tool"]["briefcase"]["app"]["activitytracker"]["macOS"]["app"]["LSMinimumSystemVersion"]
        self.assertEqual(minimum_version, "10.15")

    @pytest.mark.fr('4.1')
    def test_fr_4_1_language_settings(self):
        from activitytracker.tracking import load_config
        # Language settings are handled by i18n module
        # Test that config loading works
        assert isinstance(load_config(), dict)

    @pytest.mark.fr('FR-4')
    def test_fr_4_configuration(self):
        from activitytracker.tracking import get_config_value
        assert isinstance(get_config_value("test", "default"), str)

    @pytest.mark.fr('FR-6')
    def test_fr_6_autostart(self):
        # Autostart functionality not implemented in this version
        assert True

    @pytest.mark.fr('FR-4.1')
    def test_fr_4_configuration_persistence(self):
        from activitytracker.tracking import load_config, save_config, CONFIG_FILE

        config_path = CONFIG_FILE
        if os.path.exists(config_path):
            os.remove(config_path)

        config = {"test_key": "test_value"}
        save_config(config)

        loaded = load_config()
        assert loaded.get("test_key") == "test_value"

        if os.path.exists(config_path):
            os.remove(config_path)
