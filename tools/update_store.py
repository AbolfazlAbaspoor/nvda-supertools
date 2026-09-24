"""
Where the add-on stands in the NVDA Add-on Store, and how to move it on.

    python tools/update_store.py              where every submission stands
    python tools/update_store.py --submit     publish this version and open the form
    python tools/update_store.py --dry-run    what --submit would do, without doing it

Without arguments it only reads: which versions are live in the store, which
submissions are still waiting, and what the store's own robot last said about
them. Nothing is published unless you ask for it with --submit.

Why the last step is a button and not a line of this script: the store's
automation runs when the label 'autoSubmissionFromIssue' is put on the issue,
and that label is only applied by the issue form itself. An issue opened
through the API by someone without write access to that repository gets no
label, so nothing would ever run - the submission would sit there unread. So
this does everything up to the form, fills every field in, and leaves you one
button to press.

Nothing outside the standard library is needed.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import release  # noqa: E402  the release itself, not written twice

STORE = "nvaccess/addon-datastore"
SEARCH = "https://api.github.com/search/issues"
CONTENTS = "https://api.github.com/repos/{}/contents/addons/{}"


def get(url):
    """Read something public from GitHub. None when it is not there."""
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "SuperTools release script",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        release.say("  GitHub answered {} for {}".format(error.code, url))
        return None
    except Exception as ex:
        release.say("  could not reach GitHub: {}".format(ex))
        return None


def live_versions(name):
    """The versions of this add-on the store is serving, newest last."""
    listing = get(CONTENTS.format(STORE, name))
    if not listing:
        return []
    versions = [os.path.splitext(item["name"])[0] for item in listing
                if item["name"].endswith(".json")]
    return sorted(versions, key=release.version_tuple)


def submissions(name):
    """Every submission issue for this add-on, newest first."""
    query = 'repo:{} is:issue in:body "{}"'.format(STORE, name)
    found = get(SEARCH + "?" + urllib.parse.urlencode(
        {"q": query, "sort": "created", "order": "desc", "per_page": 20}))
    return (found or {}).get("items", [])


def last_word(number):
    """The last thing anybody said on a submission, robot or person."""
    comments = get("https://api.github.com/repos/{}/issues/{}/comments".format(
        STORE, number))
    if not comments:
        return "", ""
    latest = comments[-1]
    text = " ".join(latest.get("body", "").split())
    if "---" in text:
        text = text.split("---")[0].strip()
    return latest.get("user", {}).get("login", ""), text


def status(fields):
    name, version = fields["name"], fields["version"]
    release.say("SuperTools {} - where it stands".format(version))
    release.say("")

    live = live_versions(name)
    if live:
        release.say("In the store: " + ", ".join(live))
        if version in live:
            release.say("  this version is already there; raise it before submitting again")
    else:
        release.say("In the store: nothing yet")
    release.say("")

    issues = submissions(name)
    if not issues:
        release.say("No submission has been made yet.")
    for issue in issues:
        release.say("#{} {} [{}]".format(issue["number"], issue["title"], issue["state"]))
        release.say("  " + issue["html_url"])
        who, said = last_word(issue["number"])
        if said:
            release.say("  last word from {}: {}".format(who, said[:300]))
        release.say("")

    release.say(verdict(live, issues))
    return 0


def verdict(live, issues):
    """
    The one line worth hearing first.

    The answer to a submission never arrives as a letter saying yes. The issue
    is simply closed, its pull request merges, and the version turns up in the
    store; so that is what is looked for, rather than words.
    """
    waiting = [issue for issue in issues if issue["state"] == "open"]
    if live and not waiting:
        return ("ACCEPTED. Version {} is in the store. GitHub closed the "
                "submission when it went in.".format(live[-1]))
    if live and waiting:
        return ("Version {} is in the store, and a newer submission is still "
                "waiting.".format(live[-1]))
    if waiting:
        return ("WAITING. The first submission of an add-on waits for a person at "
                "NV Access to approve you as its publisher, which can take up to "
                "two weeks. Nothing is wrong while it waits, and there is nothing "
                "to do but wait. You will know it is done when the issue closes by "
                "itself and this line says ACCEPTED.")
    if issues:
        return ("Every submission is closed but nothing is in the store. Read what "
                "was said on the issue above: something was refused or withdrawn.")
    return "Nothing has been submitted yet. Use --submit when you are ready."


def main():
    parser = argparse.ArgumentParser(
        description="Where SuperTools stands in the NVDA Add-on Store.")
    parser.add_argument("--submit", action="store_true",
                        help="publish this version and open the submission form")
    parser.add_argument("--dry-run", action="store_true",
                        help="say what --submit would do, and do none of it")
    args = parser.parse_args()

    fields = release.manifest()
    if not (args.submit or args.dry_run):
        return status(fields)

    status(fields)
    release.say("-" * 60)
    sys.argv = ["release.py"] + (["--dry-run"] if args.dry_run else ["--open"])
    return release.main()


if __name__ == "__main__":
    sys.exit(main())
