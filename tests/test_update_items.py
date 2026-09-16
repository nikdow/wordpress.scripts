import os

import update_items as ui


class TestReadHeader:
    def test_reads_php_comment_header(self, make_plugin):
        path = make_plugin("akismet", header_version="5.3.1")
        php = os.path.join(path, "akismet.php")
        assert ui.read_header(php, "Version") == "5.3.1"

    def test_reads_readme_stable_tag(self, make_plugin):
        path = make_plugin("akismet", stable_tag="5.3.0")
        readme = os.path.join(path, "readme.txt")
        assert ui.read_header(readme, "Stable tag") == "5.3.0"

    def test_is_case_insensitive_on_field_name(self, make_plugin):
        path = make_plugin("akismet", header_version="5.3.1")
        php = os.path.join(path, "akismet.php")
        assert ui.read_header(php, "version") == "5.3.1"

    def test_returns_none_when_field_absent(self, make_plugin):
        path = make_plugin("akismet", header_version=None)
        readme = os.path.join(path, "readme.txt")
        assert ui.read_header(readme, "Version") is None

    def test_returns_none_when_file_missing(self, store):
        assert ui.read_header(os.path.join(store, "nope.php"), "Version") is None


class TestInstalledPluginVersion:
    def test_prefers_php_header_over_stable_tag(self, make_plugin):
        # This is the stable-tag trap: header 9.2.0, readme lags at 9.1.0.
        path = make_plugin("woocommerce", header_version="9.2.0", stable_tag="9.1.0")
        assert ui.installed_plugin_version(path) == "9.2.0"

    def test_falls_back_to_stable_tag_when_no_php_header(self, make_plugin):
        path = make_plugin("oldplugin", header_version=None, stable_tag="1.4.2")
        assert ui.installed_plugin_version(path) == "1.4.2"

    def test_finds_header_in_non_matching_filename(self, store, make_plugin):
        path = make_plugin("weird", header_version=None, stable_tag=None)
        with open(os.path.join(path, "bootstrap.php"), "w") as f:
            f.write("<?php\n/*\n * Plugin Name: Weird\n * Version: 3.1\n */\n")
        assert ui.installed_plugin_version(path) == "3.1"

    def test_returns_none_when_nothing_readable(self, make_plugin):
        path = make_plugin("empty", header_version=None, stable_tag=None)
        assert ui.installed_plugin_version(path) is None


class TestInstalledThemeVersion:
    def test_reads_style_css(self, make_theme):
        path = make_theme("twentytwentytwo", version="2.2")
        assert ui.installed_theme_version(path) == "2.2"

    def test_returns_none_without_style_css(self, make_theme):
        path = make_theme("brokentheme", version=None)
        assert ui.installed_theme_version(path) is None


class TestCompareVersions:
    def test_newer(self):
        assert ui.compare_versions("9.2.0", "9.1.0") == "newer"

    def test_not_newer_when_equal(self):
        assert ui.compare_versions("9.1.0", "9.1.0") == "not-newer"

    def test_not_newer_when_local_ahead(self):
        assert ui.compare_versions("9.1.0", "9.2.0") == "not-newer"

    def test_handles_pep440_suffixes(self):
        assert ui.compare_versions("1.2.0", "1.2.0-beta1") == "newer"

    def test_trunk_on_either_side_is_newer_when_different(self):
        assert ui.compare_versions("trunk", "1.0.0") == "newer"
        assert ui.compare_versions("1.0.0", "trunk") == "newer"

    def test_trunk_on_both_sides_is_not_newer(self):
        assert ui.compare_versions("trunk", "trunk") == "not-newer"

    def test_invalid_current(self):
        assert ui.compare_versions("1.0.0", "unknown") == "invalid"

    def test_invalid_latest(self):
        assert ui.compare_versions("not-a-version", "1.0.0") == "invalid"

    def test_none_is_invalid(self):
        assert ui.compare_versions("1.0.0", None) == "invalid"
        assert ui.compare_versions(None, "1.0.0") == "invalid"
