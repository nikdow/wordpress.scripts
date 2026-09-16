#!/usr/bin/env python3
"""Update the shared WordPress plugin and theme store on aws05.

Runs as root from cron at 06:13 and 18:13. Every item scanned gets exactly one
recorded outcome, every applied update is verified on disk before it is claimed,
and the exit code reports whether anything went wrong (0 ok, 1 partial, 2 fatal).

stdout carries a compact summary — that is what lands in root mail. Full
per-item detail goes to the log file (--log, default /var/log/wp-update-items.log).
"""
import argparse
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime

from packaging.version import InvalidVersion, Version


def read_header(path, field):
    """Pull a `Field: value` header out of the first 8KB of a file.

    Ported from check_updates.py — the character class handles the
    ` * `, `#` and `@` prefixes found in PHP and CSS comment headers.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(8192)
    except OSError:
        return None
    m = re.search(r"^[ \t/*#@]*%s:\s*(.+)$" % re.escape(field), head, re.I | re.M)
    return m.group(1).strip() if m else None


def installed_plugin_version(plugin_path):
    """Plugin header `Version:` first — it is what WordPress itself reports.

    Falls back to readme.txt `Stable tag:`, which is what the old script used
    exclusively and which can lag the actual shipped version.
    """
    slug = os.path.basename(plugin_path)
    candidates = [os.path.join(plugin_path, slug + ".php")]
    try:
        candidates += sorted(
            os.path.join(plugin_path, f)
            for f in os.listdir(plugin_path) if f.endswith(".php")
        )
    except OSError:
        return None

    for php in candidates:
        if os.path.isfile(php) and read_header(php, "Plugin Name"):
            version = read_header(php, "Version")
            if version:
                return version

    for readme in ("readme.txt", "README.txt"):
        rp = os.path.join(plugin_path, readme)
        if os.path.isfile(rp):
            version = read_header(rp, "Stable tag")
            if version:
                return version
    return None


def installed_theme_version(theme_path):
    style = os.path.join(theme_path, "style.css")
    return read_header(style, "Version") if os.path.isfile(style) else None


def compare_versions(latest, current):
    """Return "newer", "not-newer", or "invalid".

    "invalid" means a version string could not be parsed — the caller reports
    which side was bad. The old script collapsed this into a message that always
    blamed `latest_version` even when `current_version` was the malformed one.
    """
    if not latest or not current:
        return "invalid"
    if "trunk" in (latest, current):
        return "newer" if latest != current else "not-newer"
    try:
        return "newer" if Version(latest) > Version(current) else "not-newer"
    except InvalidVersion:
        return "invalid"


CURRENT          = "current"
UPDATED          = "updated"
SKIPPED_GIT      = "skipped-git"
SKIPPED_EXCLUDED = "skipped-excluded"
NOT_ON_WPORG     = "not-on-wporg"
UNKNOWN_VERSION  = "unknown-version"
FAILED_LOOKUP    = "failed-lookup"
FAILED_DOWNLOAD  = "failed-download"
FAILED_EXTRACT   = "failed-extract"
FAILED_VERIFY    = "failed-verify"

FAILURE_OUTCOMES   = {FAILED_LOOKUP, FAILED_DOWNLOAD, FAILED_EXTRACT, FAILED_VERIFY}
ATTENTION_OUTCOMES = FAILURE_OUTCOMES | {UNKNOWN_VERSION, NOT_ON_WPORG}
SKIP_OUTCOMES      = {SKIPPED_GIT, SKIPPED_EXCLUDED}


@dataclass
class Result:
    kind: str
    slug: str
    outcome: str
    installed: str = None
    latest: str = None
    detail: str = ""


def summarise(results):
    """{kind: {outcome: count}}"""
    counts = {}
    for item in results:
        counts.setdefault(item.kind, {})
        counts[item.kind][item.outcome] = counts[item.kind].get(item.outcome, 0) + 1
    return counts


def verdict(results):
    """Return (text, exit_code). 0 = all good, 1 = something failed."""
    failed = sum(1 for x in results if x.outcome in FAILURE_OUTCOMES)
    updated = sum(1 for x in results if x.outcome == UPDATED)
    if failed:
        return "FAILED (%d item%s)" % (failed, "" if failed == 1 else "s"), 1
    if updated:
        return "OK — %d updated" % updated, 0
    return "OK — nothing to do", 0


PROGRAM = "wp-update-items"
KIND_LABEL = {"plugin": "plugins", "theme": "themes"}


def render(results, log_path):
    """The compact block written to stdout — i.e. what lands in root mail."""
    lines = ["%s  %s" % (PROGRAM, datetime.now().astimezone()
                         .strftime("%Y-%m-%d %H:%M:%S %z"))]

    attention = [x for x in results if x.outcome in ATTENTION_OUTCOMES]
    if attention:
        lines.append("")
        lines.append("NEEDS ATTENTION")
        for x in attention:
            lines.append("  %-15s %-20s %s" % (x.outcome, x.slug, x.detail))

    counts = summarise(results)
    lines.append("")
    for kind in ("plugin", "theme"):
        by_outcome = counts.get(kind, {})
        skipped = sum(n for o, n in by_outcome.items() if o in SKIP_OUTCOMES)
        failed = sum(n for o, n in by_outcome.items() if o in FAILURE_OUTCOMES)
        prefix = "SUMMARY  " if kind == "plugin" else "         "
        # %-9s pads after the colon so "plugins: " and "themes:  " align.
        lines.append("%s%-9s%d current, %d updated, %d failed, %d skipped" % (
            prefix, KIND_LABEL[kind] + ":",
            by_outcome.get(CURRENT, 0), by_outcome.get(UPDATED, 0),
            failed, skipped))

    text, _ = verdict(results)
    lines.append("         verdict: %s — detail: %s" % (text, log_path))
    return "\n".join(lines)


USER_AGENT = "cbdweb-update-items/2.0 (+aws05 shared wordpress store)"
BACKOFF_SECONDS = [16, 64]      # one initial attempt plus these two retries
HTTP_TIMEOUT = 20


class NotOnWpOrg(Exception):
    """The slug is not published on wordpress.org (HTTP 404)."""


class LookupFailed(Exception):
    """The lookup could not be completed (network, 429 after retries, 5xx)."""


def _urlopen_json(url, timeout):
    """Isolated for testing — monkeypatched in the unit tests."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def fetch_json(url, *, attempts=3, sleeper=time.sleep):
    """GET and parse JSON.

    Raises NotOnWpOrg on 404 (no retry — the answer will not change) and
    LookupFailed on anything else once retries are exhausted.
    """
    last = None
    for attempt in range(attempts):
        try:
            return _urlopen_json(url, HTTP_TIMEOUT)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise NotOnWpOrg(url) from exc
            last = exc
            if exc.code == 429:
                retry_after = None
                try:
                    retry_after = int(exc.headers.get("Retry-After", ""))
                except (TypeError, ValueError):
                    retry_after = None
                delay = retry_after if retry_after is not None else \
                    BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
            else:
                delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
            last = exc
            delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]

        if attempt < attempts - 1:
            sleeper(delay)

    raise LookupFailed("%s: %s" % (url, last))


PLUGIN_API = "https://api.wordpress.org/plugins/info/1.0/%s.json"
THEME_API = "https://api.wordpress.org/themes/info/1.1/"


def _extract(data, slug):
    """Pull (version, download_link) out of a wp.org payload."""
    if not isinstance(data, dict) or data.get("error"):
        raise NotOnWpOrg(slug)
    version = data.get("version")
    link = data.get("download_link")
    if not version or not link:
        raise LookupFailed("%s: response missing version or download_link" % slug)
    return version, link


def latest_plugin(slug):
    return _extract(fetch_json(PLUGIN_API % urllib.parse.quote(slug)), slug)


def latest_theme(slug):
    # Verified 2026-09-16: version and download_link are both returned by
    # default; request[fields][...] is unnecessary.
    query = urllib.parse.urlencode({
        "action": "theme_information",
        "request[slug]": slug,
    })
    return _extract(fetch_json(THEME_API + "?" + query), slug)


def apply_zip(zip_path, directory, slug, expected_version, version_reader):
    """Extract a downloaded zip and prove the result. Returns (outcome, detail).

    Verification is the whole point: the old script printed success straight
    after extractall() without checking that anything landed.
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            tops = {name.split("/")[0] for name in archive.namelist() if name.strip("/")}
            if slug not in tops:
                return FAILED_EXTRACT, ("zip top-level is %s, expected %s"
                                        % (sorted(tops) or "empty", slug))
            archive.extractall(directory)
    except (zipfile.BadZipFile, OSError) as exc:
        return FAILED_EXTRACT, str(exc)

    target = os.path.join(directory, slug)
    if not os.path.isdir(target):
        return FAILED_EXTRACT, "%s not present after extraction" % target

    on_disk = version_reader(target)
    if on_disk != expected_version:
        return FAILED_VERIFY, "%s on disk, expected %s" % (on_disk or "?", expected_version)
    return UPDATED, "%s installed" % expected_version


def classify_item(directory, slug, kind, excluded, version_reader):
    """Decide an item's outcome without doing any network work.

    Returns a Result. An outcome of None means "keep going" — the caller
    performs the lookup and the update.
    """
    path = os.path.join(directory, slug)

    if os.path.exists(os.path.join(path, ".git")):
        return Result(kind=kind, slug=slug, outcome=SKIPPED_GIT,
                      detail="in-house, git-managed")
    if slug in excluded:
        return Result(kind=kind, slug=slug, outcome=SKIPPED_EXCLUDED,
                      detail="premium — never auto-updated")

    installed = version_reader(path)
    if not installed:
        return Result(kind=kind, slug=slug, outcome=UNKNOWN_VERSION,
                      detail="no readable version in %s" % path)

    return Result(kind=kind, slug=slug, outcome=None, installed=installed)


PLUGIN_DIR = "/home/lamp/wordpress/plugins"
THEME_DIR = "/home/lamp/wordpress/themes"

# List premium plugins to exclude
EXCLUDED_PLUGINS = [
    "newsletter-comments",
    "newsletter-import",
    "thim-core",
    "pmpro-pay-by-check",
    "paid-memberships-pro",
    "newsletter-automated",
    "newsletter-facebook",
    "newsletter-woocommerce",
    "newsletter-archive",
    "wp-mail-smtp-pro",
    "newsletter-amazon",
    "pmpro-akismet",
    "newsletter-extensions",
    "pmpro-add-member-admin",
    "newsletter-reports",
]

# List premium themes to exclude
EXCLUDED_THEMES = [
    "Avada",
    "Divi",
    "documentation-suburbia-child",
    "jolene",
    "sailing3",
    "sailing3.old",
    "salient",
    "salient10.5",
    "simpleblock",
    "spacious-pro",
    "spacious.1.4.7",
    "spacious.1.6.6",
    "suburbia",
    "supernews",
    "twentytwentytwo.bak",
]


LOOKUP_THROTTLE = 4       # seconds before every wp.org lookup
DOWNLOAD_THROTTLE = 3     # seconds before every zip download
DEFAULT_LOG = "/var/log/wp-update-items.log"

log = logging.getLogger(PROGRAM)


def setup_logging(log_path):
    """Full detail to the log file. stdout gets only the final summary block,
    printed directly — a redirect would put everything in the file and leave
    root mail empty, losing the verdict."""
    log.setLevel(logging.INFO)
    try:
        handler = logging.FileHandler(log_path)
    except OSError as exc:
        print("%s: cannot open log %s (%s) — continuing without it"
              % (PROGRAM, log_path, exc), file=sys.stderr)
        return False
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    return True


def download_and_apply(link, directory, slug, latest, version_reader):
    """Fetch the zip to a temp file, then hand off to apply_zip()."""
    time.sleep(DOWNLOAD_THROTTLE)
    fd, zip_path = tempfile.mkstemp(prefix="wp-update-", suffix=".zip")
    os.close(fd)
    try:
        req = urllib.request.Request(link, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response, \
                open(zip_path, "wb") as out:
            shutil.copyfileobj(response, out)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        os.unlink(zip_path)
        return FAILED_DOWNLOAD, "%s: %s" % (link, exc)

    try:
        return apply_zip(zip_path, directory, slug, latest, version_reader)
    finally:
        try:
            os.unlink(zip_path)
        except OSError:
            pass


def process_store(directory, kind, excluded, version_reader, lookup, dry_run):
    """Walk one store directory and return a Result for every item in it."""
    results = []
    for slug in sorted(os.listdir(directory)):
        path = os.path.join(directory, slug)
        if not os.path.isdir(path) or slug.startswith("."):
            continue

        result = classify_item(directory, slug, kind, excluded, version_reader)
        if result.outcome is not None:
            log.info("%s %s: %s (%s)", kind, slug, result.outcome, result.detail)
            results.append(result)
            continue

        # One try/except per item: a single failure can never abort the run.
        try:
            # Unconditional, and before the lookup. The old script slept only
            # after a SUCCESSFUL lookup, so under rate limiting it stopped
            # backing off and started hammering.
            time.sleep(LOOKUP_THROTTLE)
            latest, link = lookup(slug)
            result.latest = latest

            decision = compare_versions(latest, result.installed)
            if decision == "invalid":
                result.outcome = UNKNOWN_VERSION
                result.detail = ("cannot compare installed=%r with latest=%r"
                                 % (result.installed, latest))
            elif decision == "not-newer":
                result.outcome = CURRENT
                result.detail = result.installed
            elif dry_run:
                result.outcome = UPDATED
                result.detail = "WOULD UPDATE %s → %s" % (result.installed, latest)
            else:
                result.outcome, result.detail = download_and_apply(
                    link, directory, slug, latest, version_reader)

        except NotOnWpOrg:
            result.outcome = NOT_ON_WPORG
            result.detail = "not published on wordpress.org"
        except LookupFailed as exc:
            result.outcome = FAILED_LOOKUP
            result.detail = str(exc)
        except Exception as exc:                      # noqa: BLE001 — never abort
            result.outcome = FAILED_LOOKUP
            result.detail = "unexpected %s: %s" % (type(exc).__name__, exc)

        log.info("%s %s: %s (%s)", kind, slug, result.outcome, result.detail)
        results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Update the shared WordPress plugin and theme store.")
    parser.add_argument("--plugins-dir", default=PLUGIN_DIR)
    parser.add_argument("--themes-dir", default=THEME_DIR)
    parser.add_argument("--log", default=DEFAULT_LOG)
    parser.add_argument("--dry-run", action="store_true",
                        help="look up and decide, but download and write nothing")
    args = parser.parse_args()

    for directory in (args.plugins_dir, args.themes_dir):
        if not os.path.isdir(directory):
            print("%s: FATAL — store directory not found: %s" % (PROGRAM, directory),
                  file=sys.stderr)
            return 2

    setup_logging(args.log)
    log.info("=== run start (dry_run=%s) ===", args.dry_run)

    try:
        results = process_store(args.plugins_dir, "plugin", EXCLUDED_PLUGINS,
                                installed_plugin_version, latest_plugin, args.dry_run)
        results += process_store(args.themes_dir, "theme", EXCLUDED_THEMES,
                                 installed_theme_version, latest_theme, args.dry_run)
    except Exception as exc:                          # noqa: BLE001
        log.exception("fatal")
        print("%s: FATAL — %s: %s" % (PROGRAM, type(exc).__name__, exc), file=sys.stderr)
        return 2

    print(render(results, args.log))
    text, code = verdict(results)
    log.info("=== run end: %s (exit %d) ===", text, code)
    return code


if __name__ == "__main__":
    sys.exit(main())
