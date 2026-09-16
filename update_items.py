#!/usr/bin/env python3
import os
import re
import requests
from time import sleep
import zipfile
from packaging.version import InvalidVersion, Version
from abc import ABC, abstractmethod
from bs4 import BeautifulSoup


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


class Item(ABC):
    @abstractmethod
    def get_latest_item(self, name):
        """Fetch the latest version information."""

    def update_item(self, item, current_version, excluded_items, directory):
        """Common update logic for plugins and themes."""
        if item in excluded_items:
            print(f"⏭ Skipping excluded item: {item}")
            return

        latest_info = self.get_latest_item(item)
        if not latest_info:
            return

        sleep(4)

        try:
            latest_version = latest_info["version"]
            download_url = latest_info["download_link"]
            if (
                current_version == "trunk"
                or latest_version == "trunk"
                or Version(latest_version) > Version(current_version)
            ) and download_url:
                print(
                    f"⬆ Updating {item}: {current_version} → {latest_version}"
                )
                sleep(3)
                self.download_and_extract(download_url, directory, item)
            else:
                print(f"⛔ {item} is up to date ({current_version})")
        except Exception:
            print(f"⚠️  Invalid version for {item}: {latest_version}")

    def update(self, directory, excluded_items):
        """Update items by checking their versions and downloading updates."""
        installed_items = self.get_installed_versions(directory)
        for item, current_version in installed_items.items():
            self.update_item(item, current_version, excluded_items, directory)

    def get_readme_file_path(self, plugin_path):
        """Get the path to the readme file."""
        readme_files = ("readme.txt", "README.txt")

        if os.path.isdir(plugin_path):
            for readme_file in readme_files:
                file_path = os.path.join(plugin_path, readme_file)
                if os.path.isfile(file_path):
                    return file_path
        return False

    def get_installed_versions(self, directory):
        """Retrieve the currently installed plugins or themes and their versions."""
        items = {}
        for item in os.listdir(directory):
            git_path = os.path.join(directory, item, ".git")
            if os.path.exists(git_path):
                continue

            plugin_path = os.path.join(directory, item)
            readme_path = self.get_readme_file_path(plugin_path)
            if readme_path:
                version = "unknown"
                with open(
                    readme_path, "r", encoding="utf-8", errors="ignore"
                ) as f:
                    for line in f:
                        if "Stable tag:" in line:
                            version = line.split(":")[1].strip()
                            break
                items[item] = version

        sorted_versions = {k: items[k] for k in sorted(items)}
        return sorted_versions

    def download_and_extract(self, zip_url, extract_to, plugin):
        """Download and extract a ZIP file to the specified directory."""
        zip_path = "/tmp/temp.zip"
        response = requests.get(zip_url, stream=True)
        if response.status_code == 200:
            with open(zip_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024):
                    f.write(chunk)
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_to)
            os.remove(zip_path)
            print(f"✅ Updated: {os.path.join(extract_to, plugin)}")
        else:
            print(f"❌ Failed to download: {zip_url}")


class Plugin(Item):
    def get_latest_item(self, name):
        """Fetch the latest version information from the WordPress API."""
        api_url = f"https://api.wordpress.org/plugins/info/1.0/{name}.json"

        response = requests.get(api_url)

        if response.status_code == 200:
            return response.json()

        print(
            f"⚠️  API request failed for {name}: {response.status_code} {response.reason}"
        )

        print(response.text)
        return None


class Theme(Item):
    def get_latest_item(self, name):
        """Fetch the latest version information."""
        headers = {"User-Agent": "Mozilla/5.0"}
        repo_url = f"https://wordpress.org/themes/{name}"
        try:
            response = requests.get(repo_url, headers=headers)
            soup = BeautifulSoup(response.text, "html.parser")
            download_link = soup.select_one(
                "#wporg-theme-button-download"
            ).attrs["href"]
            version = soup.select_one(
                ".is-meta-version span:nth-child(2)"
            ).text

            return {"version": version, "download_link": download_link}
        except:
            print(
                f"⚠️  API request failed for {name}: {response.status_code} {response.reason}"
            )

        return None


class App:
    ITEM_CLASSES = {"plugin": Plugin, "theme": Theme}

    @classmethod
    def execute(cls, item, directory, excluded_items):
        if item not in cls.ITEM_CLASSES:
            raise ValueError(
                f"Invalid item: '{item}'. Valid options are {', '.join(cls.ITEM_CLASSES.keys())}."
            )

        item_obj = getattr(cls.ITEM_CLASSES[item](), "update")
        return item_obj(directory, excluded_items)


if __name__ == "__main__":
    print("🔄 Updating plugins...")
    App.execute("plugin", PLUGIN_DIR, EXCLUDED_PLUGINS)

    print("🔄 Updating themes...")
    App.execute("theme", THEME_DIR, EXCLUDED_THEMES)
