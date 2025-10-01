#!/usr/bin/env python3
#
# Upgrade WP core to the latest minor version
#
# backup changes to this file by copying it into https://doc.cbdweb.net/documentation/technical/word-press/combined-wp-core/

import re
from bs4 import BeautifulSoup
import http.client
from packaging.version import Version
import subprocess
import sys
import os


def run_cmd(cmd):
    output = subprocess.getoutput(cmd)
    status = subprocess.getstatusoutput(cmd)[0]
    if 0 != status:
        print("  > cmd %s failed with status code %d" % (cmd, status))
        sys.exit(-1)
    return output


def getCurrentVersion(dir):
    file = os.path.join(dir, "wp-includes/version.php")
    with open(file, encoding="utf-8") as f:
        versions = re.findall("\$wp_version = '([\d\.]+)'", f.read())
        if len(versions) > 0:
            return versions[0]


def getLatestTags():
    conn = http.client.HTTPSConnection("core.svn.wordpress.org", 443)
    conn.request("GET", "/tags/")
    r1 = conn.getresponse()
    html_doc = r1.read().decode("utf-8")
    soup = BeautifulSoup(html_doc, 'html.parser')
    return [a.get('href').replace('/', '') for a in soup.find_all('a')]


def getLatestReleases():
    releases = []
    conn = http.client.HTTPSConnection("wordpress.org", 443)
    conn.request("GET", "/download/releases/")
    html_doc = conn.getresponse().read().decode("utf-8")
    soup = BeautifulSoup(html_doc, 'html.parser')

    for table in soup.find_all('div', id='latest'):
        table = table.find('tbody')
        for tr in table.find_all('tr'):
            if tr is None:
                continue
            tds = tr.find_all(recursive=False)
            releases.append((tds[0].get_text(),
                             tds[1].get_text(),
                             tds[2].find('a').get('href') if tds[2].find('a') is not None else '',
                             tds[3].find('a').get('href') if tds[3].find('a') is not None else ''))
    releases.reverse()
    return releases


def toMajorVersion(curVersion):
    v = curVersion.split(".")
    majorVersion = v[0] + "." + v[1]
    return majorVersion


def getLatestMinorRelease(curVersion):
    for tag in getLatestReleases():
        m = re.match(b'^\d+[\d.]*', tag[0].encode("utf-8"))
        if m is None:
            continue
        if Version(tag[0]) > Version(curVersion):
            return tag
        else:
            print("Latest version installed")
            return
    else:
        print("No latest release found.")


def upgradeWpDir(dir):
    print("Checking for updating core %s ..." % dir)
    curVersion = getCurrentVersion(dir)
    if not curVersion:
        print("Failed to extract WP version !!!")
        return
    print("Current WP version: ", curVersion)

    release = getLatestMinorRelease(curVersion)
    if release is None:
        print("No update needed")
        return 0

    print('Latest Release found:', release)

    minorUpdate = False
    majorVersion = toMajorVersion(release[0])
    if curVersion.find(majorVersion) == 0:
        print('%s is a minor update ...' % release[0])
        minorUpdate = True
    elif os.path.exists(os.path.join(dir, '..', 'wp' + majorVersion)):
        print('%s is a major update which is already locally available, going to skip it.' % release[0])
        return

    print('Downloading release %s ...' % release[3])
    subprocess.getstatusoutput("rm -rf release.tar.gz")
    download_url = release[3]
    wget_command = ["wget", "-O", "release.tar.gz", download_url]
    print('Download command:', ' '.join(wget_command))  # Print the wget command for debugging

    try:
        subprocess.run(wget_command, check=True)
    except subprocess.CalledProcessError as e:
        print('Error: failed to download.')
        print('wget output:', e.output.decode('utf-8'))
        exit(1)

    print('Extracting ... ')
    status, output = subprocess.getstatusoutput("tar -xzf release.tar.gz")
    if status:
        print('Error: failed to extract ...')
        print(output)
        exit(1)

    target = "wordpress"

    print("copy .htaccess ...")
    status, output = subprocess.getstatusoutput("cp %s/.htaccess %s/.htaccess" % (dir, target))
    if status:
        print('Failed to copy .htaccess')
        print(output)
        exit(1)

    print('Copying wp-config ...')
    status, output = subprocess.getstatusoutput("cp %s/wp-config.php %s/wp-config.php" % (dir, target))
    if status:
        print('Failed to copy wp-config')
        print(output)
        exit(1)

    print('Copying robots.txt ...')
    status, output = subprocess.getstatusoutput("cp %s/robots.txt %s/robots.txt" % (dir, target))
    if status:
        print('Failed to copy: robots.txt')
        print(output)
        exit(1)

    print('Chown ...')
    status, output = subprocess.getstatusoutput("chown -R root:root %s" % target)
    if status:
        print('Failed to chown')
        print(output)
        exit(1)

    print('rm wp-content ...')
    status, output = subprocess.getstatusoutput("rm -R %s/wp-content/" % target)
    if status:
        print('Failed to rm wp-content')
        exit(1)

    print('ln ../wp-content ...')
    status, output = subprocess.getstatusoutput("ln -s ../../wp-content/ %s/wp-content" % target)
    if status:
        print('Failed to ln ../wp-content')
        print(output)
        exit(1)

    print('Backup tar ...')
    status, output = subprocess.getstatusoutput("tar -zcvf %s-2020-05-02.tar.gz %s" % (dir, dir))
    if status:
        print('Failed to tar -xvf ...')
        print(output)
        return

    # only remove in case of minorUpdate
    if minorUpdate:
        print('Remove dir %s ...' % dir)
        status, output = subprocess.getstatusoutput("rm -rf %s" % dir)
        if status:
            print('Failed to remove dir')
            print(output)
            return

    cmd = "mv wordpress wp" + toMajorVersion(release[0])
    print(cmd)
    status, output = subprocess.getstatusoutput(cmd)
    if status:
        print('Error: failed to mv to dir wp', toMajorVersion(release[0]))
        print(output)
        exit(1)

    subprocess.getstatusoutput("rm -rf *.tar.gz")

    cmd = "service php8.3-fpm reload"
    print(cmd)
    subprocess.getstatusoutput(cmd)


coreDir = "/home/lamp/wordpress/core"
os.chdir(coreDir)
print("Working Dir: ", os.getcwd())

for dir in os.listdir(coreDir):
    dirPath = os.path.join(coreDir, dir)
    if dir.find('wp') == 0 and os.path.isdir(dirPath):
        upgradeWpDir(dirPath)
        print('-----------------------------------')
