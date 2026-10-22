import os
import subprocess
import tarfile
import types

import pytest

from conftest import write

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "upgrade_minor.py")

RELEASES = {
    "latest": [("7.1.3", "October 6, 2026", "", "https://wordpress.org/wordpress-7.1.3.tar.gz")],
    "branch-71": [("7.1.3", "", "", ""), ("7.1.2", "", "", ""), ("7.1.1", "", "", ""), ("7.1", "", "", "")],
    "branch-70": [("7.0.7", "", "", ""), ("7.0.6", "", "", ""), ("7.0.5", "", "", ""), ("7.0.4", "", "", "")],
}


def load():
    """upgrade_minor.py's functions, without the cron body that chdirs into /home/lamp."""
    with open(SCRIPT, encoding="utf-8") as f:
        src = f.read().split("\ncoreDir = ")[0]
    ns = {"__name__": "upgrade_minor"}
    exec(compile(src, SCRIPT, "exec"), ns)
    return ns


@pytest.fixture
def um():
    ns = load()
    ns["getLatestReleases"] = lambda section="latest": list(RELEASES.get(section, []))
    return ns


class TestGetLatestMinorRelease:
    def test_picks_newest_in_own_branch_when_a_newer_branch_exists(self, um):
        # the bug: wp7.0 sat at 7.0.4 because only the "latest" (7.1.3) table was checked
        assert um["getLatestMinorRelease"]("7.0.4")[0] == "7.0.7"

    def test_picks_newest_regardless_of_table_order(self, um):
        RELEASES_REVERSED = dict(RELEASES, **{"branch-70": list(reversed(RELEASES["branch-70"]))})
        um["getLatestReleases"] = lambda section="latest": list(RELEASES_REVERSED.get(section, []))
        assert um["getLatestMinorRelease"]("7.0.5")[0] == "7.0.7"

    def test_falls_back_to_latest_when_branch_is_current(self, um):
        # a newer major is still offered, upgradeWpDir decides whether to stage it
        assert um["getLatestMinorRelease"]("7.0.7")[0] == "7.1.3"

    def test_falls_back_to_latest_when_branch_table_missing(self, um):
        assert um["getLatestMinorRelease"]("6.9.4")[0] == "7.1.3"

    def test_none_when_up_to_date(self, um):
        assert um["getLatestMinorRelease"]("7.1.3") is None


@pytest.fixture
def core(tmp_path, monkeypatch):
    """A core dir holding wp7.0 at 7.0.4, a 7.0.7 release tarball, and the shared wp-content."""
    core = tmp_path / "core"
    site = core / "wp7.0"
    write(str(site / "wp-includes" / "version.php"), "<?php\n$wp_version = '7.0.4';\n")
    write(str(site / ".htaccess"), "# site htaccess\n")
    write(str(site / "wp-config.php"), "<?php // site config\n")
    write(str(site / "robots.txt"), "User-agent: *\n")
    os.makedirs(str(tmp_path / "wp-content"))
    os.symlink("../../wp-content/", str(site / "wp-content"))

    release = tmp_path / "release"
    write(str(release / "wordpress" / "wp-includes" / "version.php"), "<?php\n$wp_version = '7.0.7';\n")
    write(str(release / "wordpress" / "wp-content" / "index.php"), "<?php\n")
    tarball = str(tmp_path / "wordpress-7.0.7.tar.gz")
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(str(release / "wordpress"), arcname="wordpress")

    monkeypatch.chdir(str(core))
    return types.SimpleNamespace(dir=str(core), site=str(site), tarball=tarball)


def run_upgrade(um, core, systemctl_units=(0, "php8.4-fpm.service loaded active running The PHP 8.4 FastCGI Process Manager")):
    """Run upgradeWpDir with the network, chown and systemctl stubbed; returns the reload commands issued."""
    reloads = []

    def getstatusoutput(cmd):
        if cmd.startswith("chown"):
            return 0, ""
        if cmd.startswith("systemctl list-units"):
            return systemctl_units
        if cmd.startswith("systemctl reload"):
            reloads.append(cmd)
            return 0, ""
        return subprocess.getstatusoutput(cmd)

    def run(cmd, check=False):
        assert cmd[:3] == ["wget", "-O", "release.tar.gz"]
        subprocess.run(["cp", core.tarball, "release.tar.gz"], check=True)

    um["subprocess"] = types.SimpleNamespace(getstatusoutput=getstatusoutput, getoutput=subprocess.getoutput,
                                             run=run, CalledProcessError=subprocess.CalledProcessError)
    um["getLatestMinorRelease"] = lambda cur: ("7.0.7", "October 6, 2026", "", "https://wordpress.org/wordpress-7.0.7.tar.gz")
    um["upgradeWpDir"](core.site)
    return reloads


class TestUpgradeWpDir:
    def test_minor_upgrade_keeps_site_files(self, um, core):
        run_upgrade(um, core)
        assert um["getCurrentVersion"](core.site) == "7.0.7"
        for name, content in [(".htaccess", "# site htaccess\n"), ("wp-config.php", "<?php // site config\n"),
                              ("robots.txt", "User-agent: *\n")]:
            with open(os.path.join(core.site, name), encoding="utf-8") as f:
                assert f.read() == content
        assert os.readlink(os.path.join(core.site, "wp-content")) == "../../wp-content/"
        assert not os.path.exists(os.path.join(core.dir, "wordpress"))

    def test_keeps_well_known(self, um, core):
        write(os.path.join(core.site, ".well-known", "acme-challenge", "token"), "abc\n")
        run_upgrade(um, core)
        with open(os.path.join(core.site, ".well-known", "acme-challenge", "token"), encoding="utf-8") as f:
            assert f.read() == "abc\n"

    def test_no_well_known_is_fine(self, um, core):
        run_upgrade(um, core)
        assert not os.path.exists(os.path.join(core.site, ".well-known"))

    def test_reloads_each_active_fpm(self, um, core):
        units = (0, "php8.4-fpm.service loaded active running PHP 8.4\nphp8.5-fpm.service loaded active running PHP 8.5\n")
        assert run_upgrade(um, core, units) == ["systemctl reload php8.4-fpm.service",
                                                "systemctl reload php8.5-fpm.service"]

    def test_no_reload_when_listing_fails(self, um, core, capsys):
        assert run_upgrade(um, core, (127, "sh: systemctl: command not found")) == []
        assert "No active php-fpm service found to reload" in capsys.readouterr().out
