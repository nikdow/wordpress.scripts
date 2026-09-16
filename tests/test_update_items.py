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


def r(outcome, kind="plugin", slug="x", **kw):
    return ui.Result(kind=kind, slug=slug, outcome=outcome, **kw)


class TestSummarise:
    def test_counts_by_kind_and_outcome(self):
        results = [
            r(ui.CURRENT), r(ui.CURRENT),
            r(ui.UPDATED),
            r(ui.SKIPPED_GIT),
            r(ui.CURRENT, kind="theme"),
        ]
        counts = ui.summarise(results)
        assert counts["plugin"][ui.CURRENT] == 2
        assert counts["plugin"][ui.UPDATED] == 1
        assert counts["plugin"][ui.SKIPPED_GIT] == 1
        assert counts["theme"][ui.CURRENT] == 1


class TestVerdict:
    def test_clean_noop_is_exit_zero(self):
        text, code = ui.verdict([r(ui.CURRENT), r(ui.SKIPPED_EXCLUDED)])
        assert code == 0
        assert "nothing to do" in text

    def test_successful_updates_are_exit_zero(self):
        text, code = ui.verdict([r(ui.UPDATED), r(ui.CURRENT)])
        assert code == 0
        assert "1 updated" in text

    def test_any_failure_is_exit_one(self):
        text, code = ui.verdict([r(ui.CURRENT), r(ui.FAILED_VERIFY)])
        assert code == 1
        assert "FAILED" in text

    def test_all_four_failure_kinds_count(self):
        for outcome in (ui.FAILED_LOOKUP, ui.FAILED_DOWNLOAD,
                        ui.FAILED_EXTRACT, ui.FAILED_VERIFY):
            _, code = ui.verdict([r(outcome)])
            assert code == 1, outcome

    def test_not_on_wporg_does_not_fail_the_run(self):
        _, code = ui.verdict([r(ui.NOT_ON_WPORG), r(ui.CURRENT)])
        assert code == 0

    def test_unknown_version_does_not_fail_the_run(self):
        _, code = ui.verdict([r(ui.UNKNOWN_VERSION)])
        assert code == 0


LOG = "/var/log/wp-update-items.log"


class TestRender:
    def test_clean_run_omits_attention_block(self):
        out = ui.render([r(ui.CURRENT), r(ui.CURRENT, kind="theme")], LOG)
        assert "NEEDS ATTENTION" not in out
        assert "verdict: OK — nothing to do" in out
        assert LOG in out

    def test_failures_appear_in_attention_block(self):
        results = [
            r(ui.FAILED_VERIFY, slug="woocommerce",
              installed="9.1.2", latest="9.2.0",
              detail="9.1.2 on disk, expected 9.2.0"),
            r(ui.CURRENT, slug="akismet"),
        ]
        out = ui.render(results, LOG)
        assert "NEEDS ATTENTION" in out
        assert "woocommerce" in out
        assert "9.1.2 on disk, expected 9.2.0" in out
        assert "akismet" not in out          # healthy items stay out of stdout
        assert "verdict: FAILED (1 item)" in out

    def test_summary_line_per_kind(self):
        results = [r(ui.CURRENT), r(ui.UPDATED), r(ui.SKIPPED_GIT),
                   r(ui.CURRENT, kind="theme")]
        out = ui.render(results, LOG)
        assert "plugins: 1 current, 1 updated, 0 failed, 1 skipped" in out
        assert "themes:  1 current, 0 updated, 0 failed, 0 skipped" in out

    def test_not_on_wporg_shown_but_run_still_ok(self):
        out = ui.render([r(ui.NOT_ON_WPORG, slug="sailing4")], LOG)
        assert "sailing4" in out
        assert "verdict: OK" in out
