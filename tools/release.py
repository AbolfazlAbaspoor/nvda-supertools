"""
Publish a version and submit it to the NVDA Add-on Store.

    python tools/release.py               build, release on GitHub, print the form
    python tools/release.py --open        the same, and open the form in a browser
    python tools/release.py --dry-run     say what would happen, change nothing
    python tools/release.py --form-only   the release exists already, just the form

Every store update is the same short form: a download address, the source
address, the publisher, the channel and the licence. Everything else - the
version, the description, the translations, the checksum - the store reads out
of the file you point it at, so this script's real job is to make that file,
put it somewhere permanent, and hand you a form that is already filled in.

Only the first submission of an add-on waits for a person; after that the
checks are automatic.

Nothing outside the standard library is needed. A GitHub token is taken from
GITHUB_TOKEN, or from the credentials git already uses for pushing.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
FORM = "https://github.com/nvaccess/addon-datastore/issues/new"
API_VERSIONS = ("https://raw.githubusercontent.com/nvaccess/addon-datastore/"
                "master/transform/nvdaAPIVersions.json")


def say(text=""):
    print(text, flush=True)


def fail(text):
    say("")
    say("Stopped: " + text)
    sys.exit(1)


# -- What we are publishing --------------------------------------------------

def manifest():
    """The manifest as a plain dictionary."""
    fields = {}
    with open(os.path.join(ROOT, "manifest.ini"), encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                fields[key.strip()] = value.strip().strip('"')
    return fields


def build_vars():
    """The licence and the addresses, from buildVars.py, without importing it."""
    text = open(os.path.join(ROOT, "buildVars.py"), encoding="utf-8").read()
    return dict(re.findall(r'"(addon_\w+)":\s*"([^"]*)"', text))


def repository(url):
    """("AbolfazlAbaspoor", "nvda-supertools") from the address in the manifest."""
    parts = urllib.parse.urlparse(url).path.strip("/").split("/")
    if len(parts) < 2:
        fail("the url in manifest.ini is not a GitHub repository: " + url)
    return parts[0], parts[1].replace(".git", "")


def release_notes(version):
    """What the readme says changed in this version, for the release page."""
    text = open(os.path.join(ROOT, "readme.md"), encoding="utf-8").read()
    match = re.search(r"^### " + re.escape(version) + r"\s*$(.*?)^#{2,3} ",
                      text, re.S | re.M)
    return match.group(1).strip() if match else ""


# -- Checks the store will make anyway ---------------------------------------

def api_versions():
    """The NVDA versions the store accepts; empty if we cannot reach it."""
    try:
        with urllib.request.urlopen(API_VERSIONS, timeout=25) as response:
            return json.load(response)
    except Exception:
        return []


def version_tuple(version):
    """"1.10.2" -> (1, 10, 2), so versions sort the way people read them."""
    parts = [int("".join(c for c in piece if c.isdigit()) or 0)
             for piece in str(version).split(".")]
    return tuple(parts + [0, 0, 0])[:3]


def version_text(entry):
    return "{major}.{minor}.{patch}".format(**entry)


def check(fields, variables):
    """Everything the store validates, checked here so a failure costs seconds."""
    name, version = fields.get("name", ""), fields.get("version", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        fail("the add-on name may only hold letters, numbers, _ and -: " + name)
    if not re.fullmatch(r"\d+\.\d+(\.\d+)?", version):
        fail("the version must be major.minor or major.minor.patch: " + version)
    if not fields.get("url", "").startswith("https://"):
        fail("every address must start with https://, but url is "
             + fields.get("url", ""))
    for key in ("addon_url", "addon_licenseURL", "addon_sourceURL"):
        value = variables.get(key, "")
        if value and "://" in value and not value.startswith("https://"):
            fail("every address must start with https://, but {} is {}".format(
                key, value))

    channel = "stable"
    versions = api_versions()
    if versions:
        known = {version_text(item["apiVer"]): item for item in versions}
        for key in ("minimumNVDAVersion", "lastTestedNVDAVersion"):
            asked = fields.get(key, "")
            padded = asked if asked.count(".") == 2 else asked + ".0"
            if padded not in known:
                fail("{} is {}, which the store does not know. The versions it "
                     "accepts are listed in nvdaAPIVersions.json.".format(key, asked))
            if key == "lastTestedNVDAVersion" and known[padded].get("experimental"):
                channel = "beta"
                say("  note: NVDA {} is still experimental, so the channel is beta"
                    .format(asked))
    else:
        say("  note: could not reach the store to check the NVDA versions")
    return channel


# -- Talking to GitHub -------------------------------------------------------

def token():
    """The token, from the environment or from the one git pushes with."""
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
    try:
        answer = subprocess.run(["git", "credential", "fill"], cwd=ROOT,
                                input="protocol=https\nhost=github.com\n\n",
                                capture_output=True, text=True, timeout=30)
        for line in answer.stdout.splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    fail("no GitHub token. Set GITHUB_TOKEN, or push once so git remembers one.")


def request(method, url, secret, data=None, content_type="application/json",
            upload=None, quiet=False):
    body = upload if upload is not None else (
        json.dumps(data).encode("utf-8") if data is not None else None)
    call = urllib.request.Request(url, data=body, method=method)
    call.add_header("Authorization", "Bearer " + secret)
    call.add_header("Accept", "application/vnd.github+json")
    if body is not None:
        call.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(call, timeout=120) as response:
            text = response.read().decode("utf-8")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as error:
        if quiet:
            return None
        detail = error.read().decode("utf-8", "replace")[:400]
        fail("GitHub said {} for {}\n{}".format(error.code, url, detail))


# -- The work ----------------------------------------------------------------

def build():
    say("Building.")
    result = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build.py")],
                            cwd=ROOT)
    if result.returncode:
        fail("the build did not finish; nothing was published")


def main():
    parser = argparse.ArgumentParser(description="Publish a version of SuperTools.")
    parser.add_argument("--open", action="store_true",
                        help="open the submission form in a browser")
    parser.add_argument("--dry-run", action="store_true",
                        help="say what would happen, publish nothing")
    parser.add_argument("--form-only", action="store_true",
                        help="the release already exists; only print the form")
    args = parser.parse_args()

    fields, variables = manifest(), build_vars()
    version = fields["version"]
    owner, repo = repository(fields["url"])
    tag = "v" + version
    asset = "SuperTools-{}.nvda-addon".format(version)
    path = os.path.join(ROOT, asset)

    say("SuperTools {} -> {}/{}".format(version, owner, repo))
    channel = check(fields, variables)

    if not (args.form_only or args.dry_run):
        build()
        if not os.path.isfile(path):
            fail("no " + asset + " to publish")
    digest = ""
    if os.path.isfile(path):
        digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
        say("  {} ({:.0f} KB)".format(asset, os.path.getsize(path) / 1024))
        say("  sha256 {}".format(digest))

    download = "https://github.com/{}/{}/releases/download/{}/{}".format(
        owner, repo, tag, asset)

    if args.dry_run:
        say("")
        say("Would tag {}, publish {} and submit {}".format(tag, asset, download))
    elif not args.form_only:
        secret = token()
        say("Publishing the release.")
        release = request("GET", "{}/repos/{}/{}/releases/tags/{}".format(
            API, owner, repo, tag), secret, quiet=True)
        if release:
            say("  {} is already there; replacing the file".format(tag))
            for old in release.get("assets", []):
                if old["name"] == asset:
                    request("DELETE", "{}/repos/{}/{}/releases/assets/{}".format(
                        API, owner, repo, old["id"]), secret)
        else:
            release = request(
                "POST", "{}/repos/{}/{}/releases".format(API, owner, repo), secret,
                {"tag_name": tag, "name": "SuperTools " + version,
                 "body": release_notes(version), "draft": False,
                 "prerelease": channel != "stable"})
            say("  released as " + tag)
        request("POST", "{}/repos/{}/{}/releases/{}/assets?name={}".format(
            UPLOADS, owner, repo, release["id"], urllib.parse.quote(asset)),
            secret, content_type="application/octet-stream",
            upload=open(path, "rb").read())
        say("  uploaded " + asset)

        say("Checking that the store can download it.")
        try:
            with urllib.request.urlopen(download, timeout=60) as response:
                got = response.read()
            if hashlib.sha256(got).hexdigest() != digest:
                fail("what downloads from that address is not the file we built")
            say("  the address works and gives the same file")
        except urllib.error.HTTPError as error:
            fail("the download address answered {}. If the repository is still "
                 "private, make it public and run this again.".format(error.code))

    query = urllib.parse.urlencode({
        "template": "registerAddon.yml",
        "title": "[Submit add-on]: SuperTools {}".format(version),
        "download-url": download,
        "source-url": fields["url"],
        "publisher": variables.get("addon_author",
                                   fields.get("author", "")).split("<")[0].strip(),
        "channel": channel,
        "license-name": variables.get("addon_license", "GPL v2"),
        "license-url": variables.get("addon_licenseURL",
                                     "https://www.gnu.org/licenses/gpl-2.0.html"),
    })
    url = FORM + "?" + query

    say("")
    say("The submission form, already filled in:")
    say(url)
    say("")
    say("Open it, read it once and press the button at the bottom. The store")
    say("downloads the file, scans it, checks it and opens the pull request by")
    say("itself. The first time, a person has to approve you as the publisher of")
    say("this add-on, which can take up to two weeks; after that it is automatic.")
    if args.open:
        import webbrowser
        webbrowser.open(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
