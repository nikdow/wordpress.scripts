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
