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


import io
import urllib.error

import pytest


def http_error(code, headers=None):
    return urllib.error.HTTPError(
        "http://x", code, "err", headers or {}, io.BytesIO(b""))


class TestFetchJson:
    def test_returns_parsed_json(self, monkeypatch):
        monkeypatch.setattr(ui, "_urlopen_json", lambda url, timeout: {"version": "1.0"})
        assert ui.fetch_json("http://x") == {"version": "1.0"}

    def test_404_raises_not_on_wporg(self, monkeypatch):
        def boom(url, timeout):
            raise http_error(404)
        monkeypatch.setattr(ui, "_urlopen_json", boom)
        with pytest.raises(ui.NotOnWpOrg):
            ui.fetch_json("http://x")

    def test_404_does_not_retry(self, monkeypatch):
        calls = []
        def boom(url, timeout):
            calls.append(1)
            raise http_error(404)
        monkeypatch.setattr(ui, "_urlopen_json", boom)
        with pytest.raises(ui.NotOnWpOrg):
            ui.fetch_json("http://x")
        assert len(calls) == 1

    def test_429_retries_then_fails(self, monkeypatch):
        calls, slept = [], []
        def boom(url, timeout):
            calls.append(1)
            raise http_error(429)
        monkeypatch.setattr(ui, "_urlopen_json", boom)
        with pytest.raises(ui.LookupFailed):
            ui.fetch_json("http://x", sleeper=slept.append)
        assert len(calls) == 3           # one attempt plus two retries
        assert slept == [16, 64]

    def test_429_honours_retry_after(self, monkeypatch):
        slept = []
        def boom(url, timeout):
            raise http_error(429, {"Retry-After": "7"})
        monkeypatch.setattr(ui, "_urlopen_json", boom)
        with pytest.raises(ui.LookupFailed):
            ui.fetch_json("http://x", sleeper=slept.append)
        assert slept == [7, 7]

    def test_429_then_success(self, monkeypatch):
        state = {"n": 0}
        def flaky(url, timeout):
            state["n"] += 1
            if state["n"] == 1:
                raise http_error(429)
            return {"version": "2.0"}
        monkeypatch.setattr(ui, "_urlopen_json", flaky)
        assert ui.fetch_json("http://x", sleeper=lambda s: None) == {"version": "2.0"}

    def test_500_retries_then_lookup_failed(self, monkeypatch):
        def boom(url, timeout):
            raise http_error(500)
        monkeypatch.setattr(ui, "_urlopen_json", boom)
        with pytest.raises(ui.LookupFailed):
            ui.fetch_json("http://x", sleeper=lambda s: None)


class TestLookups:
    def test_plugin_lookup_builds_url_and_extracts_fields(self, monkeypatch):
        seen = {}
        def fake(url, **kw):
            seen["url"] = url
            return {"version": "5.3.1",
                    "download_link": "https://downloads.wordpress.org/plugin/akismet.5.3.1.zip"}
        monkeypatch.setattr(ui, "fetch_json", fake)
        version, link = ui.latest_plugin("akismet")
        assert version == "5.3.1"
        assert link.endswith("akismet.5.3.1.zip")
        assert seen["url"] == "https://api.wordpress.org/plugins/info/1.0/akismet.json"

    def test_theme_lookup_builds_url_and_extracts_fields(self, monkeypatch):
        seen = {}
        def fake(url, **kw):
            seen["url"] = url
            return {"version": "2.2",
                    "download_link": "https://downloads.wordpress.org/theme/twentytwentytwo.2.2.zip"}
        monkeypatch.setattr(ui, "fetch_json", fake)
        version, link = ui.latest_theme("twentytwentytwo")
        assert version == "2.2"
        assert link.endswith("twentytwentytwo.2.2.zip")
        assert "action=theme_information" in seen["url"]
        assert "request%5Bslug%5D=twentytwentytwo" in seen["url"]

    def test_plugin_error_body_raises_not_on_wporg(self, monkeypatch):
        monkeypatch.setattr(ui, "fetch_json", lambda url, **kw: {"error": "Plugin not found."})
        with pytest.raises(ui.NotOnWpOrg):
            ui.latest_plugin("nope")

    def test_missing_download_link_raises_lookup_failed(self, monkeypatch):
        monkeypatch.setattr(ui, "fetch_json", lambda url, **kw: {"version": "1.0"})
        with pytest.raises(ui.LookupFailed):
            ui.latest_plugin("weird")

    def test_slug_is_url_quoted(self, monkeypatch):
        seen = {}
        def fake(url, **kw):
            seen["url"] = url
            return {"version": "1.0", "download_link": "http://x/y.zip"}
        monkeypatch.setattr(ui, "fetch_json", fake)
        ui.latest_plugin("odd name")
        assert "odd%20name" in seen["url"]


import zipfile


def make_zip(path, slug, version):
    """A plugin zip shaped like wordpress.org ships them."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("%s/%s.php" % (slug, slug),
                   "<?php\n/*\n * Plugin Name: %s\n * Version: %s\n */\n" % (slug, version))


class TestApplyZip:
    def test_extracts_and_verifies(self, tmp_path, store, make_plugin):
        make_plugin("akismet", header_version="5.0.0", stable_tag=None)
        zip_path = str(tmp_path / "a.zip")
        make_zip(zip_path, "akismet", "5.3.1")

        outcome, detail = ui.apply_zip(zip_path, store, "akismet", "5.3.1",
                                       ui.installed_plugin_version)
        assert outcome == ui.UPDATED
        assert ui.installed_plugin_version(os.path.join(store, "akismet")) == "5.3.1"

    def test_missing_top_level_dir_is_failed_extract(self, tmp_path, store, make_plugin):
        make_plugin("akismet", header_version="5.0.0", stable_tag=None)
        zip_path = str(tmp_path / "a.zip")
        make_zip(zip_path, "wrong-slug", "5.3.1")

        outcome, detail = ui.apply_zip(zip_path, store, "akismet", "5.3.1",
                                       ui.installed_plugin_version)
        assert outcome == ui.FAILED_EXTRACT
        assert "wrong-slug" in detail or "akismet" in detail

    def test_version_not_changing_is_failed_verify(self, tmp_path, store, make_plugin):
        make_plugin("akismet", header_version="5.0.0", stable_tag=None)
        zip_path = str(tmp_path / "a.zip")
        make_zip(zip_path, "akismet", "5.0.0")      # zip ships the OLD version

        outcome, detail = ui.apply_zip(zip_path, store, "akismet", "5.3.1",
                                       ui.installed_plugin_version)
        assert outcome == ui.FAILED_VERIFY
        assert "5.0.0" in detail and "5.3.1" in detail

    def test_corrupt_zip_is_failed_extract(self, tmp_path, store, make_plugin):
        make_plugin("akismet", header_version="5.0.0", stable_tag=None)
        zip_path = str(tmp_path / "bad.zip")
        with open(zip_path, "wb") as f:
            f.write(b"not a zip file at all")

        outcome, detail = ui.apply_zip(zip_path, store, "akismet", "5.3.1",
                                       ui.installed_plugin_version)
        assert outcome == ui.FAILED_EXTRACT


class TestClassifyItem:
    def test_git_directory_is_skipped(self, store, make_plugin):
        path = make_plugin("membero-allow-empty-email")
        os.makedirs(os.path.join(path, ".git"))
        result = ui.classify_item(store, "membero-allow-empty-email", "plugin",
                                  [], ui.installed_plugin_version)
        assert result.outcome == ui.SKIPPED_GIT

    def test_excluded_is_skipped(self, store, make_plugin):
        make_plugin("wp-mail-smtp-pro")
        result = ui.classify_item(store, "wp-mail-smtp-pro", "plugin",
                                  ["wp-mail-smtp-pro"], ui.installed_plugin_version)
        assert result.outcome == ui.SKIPPED_EXCLUDED

    def test_no_readable_version_is_unknown(self, store, make_plugin):
        make_plugin("mystery", header_version=None, stable_tag=None)
        result = ui.classify_item(store, "mystery", "plugin", [],
                                  ui.installed_plugin_version)
        assert result.outcome == ui.UNKNOWN_VERSION

    def test_git_check_precedes_version_check(self, store, make_plugin):
        path = make_plugin("inhouse", header_version=None, stable_tag=None)
        os.makedirs(os.path.join(path, ".git"))
        result = ui.classify_item(store, "inhouse", "plugin", [],
                                  ui.installed_plugin_version)
        assert result.outcome == ui.SKIPPED_GIT


class TestProcessStoreIsolation:
    def test_one_item_exploding_does_not_stop_the_run(
            self, monkeypatch, store, make_plugin):
        make_plugin("aaa", header_version="1.0.0")
        make_plugin("bbb", header_version="1.0.0")
        make_plugin("ccc", header_version="1.0.0")

        def lookup(slug):
            if slug == "bbb":
                raise RuntimeError("simulated explosion")
            return "1.0.0", "http://example.invalid/%s.zip" % slug

        monkeypatch.setattr(ui.time, "sleep", lambda s: None)
        results = ui.process_store(store, "plugin", [],
                                   ui.installed_plugin_version, lookup,
                                   dry_run=True)

        assert len(results) == 3, "run must complete all three items"
        by_slug = {x.slug: x for x in results}
        assert by_slug["aaa"].outcome == ui.CURRENT
        assert by_slug["ccc"].outcome == ui.CURRENT
        assert by_slug["bbb"].outcome == ui.FAILED_LOOKUP
        assert "RuntimeError" in by_slug["bbb"].detail

    def test_not_on_wporg_is_isolated_too(self, monkeypatch, store, make_plugin):
        make_plugin("aaa", header_version="1.0.0")
        make_plugin("premium-thing", header_version="1.0.0")

        def lookup(slug):
            if slug == "premium-thing":
                raise ui.NotOnWpOrg(slug)
            return "1.0.0", "http://example.invalid/a.zip"

        monkeypatch.setattr(ui.time, "sleep", lambda s: None)
        results = ui.process_store(store, "plugin", [],
                                   ui.installed_plugin_version, lookup,
                                   dry_run=True)

        by_slug = {x.slug: x for x in results}
        assert by_slug["premium-thing"].outcome == ui.NOT_ON_WPORG
        assert by_slug["aaa"].outcome == ui.CURRENT
        assert ui.verdict(results)[1] == 0, "not-on-wporg must not fail the run"
