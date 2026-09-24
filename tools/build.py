"""
Build the .nvda-addon package.

    python tools/build.py

Regenerates the documentation and the gettext catalogues first, refuses to
build if a catalogue has a problem, and then zips exactly what the add-on needs
at runtime.
"""
import os
import re
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")


def run(script):
    result = subprocess.run([sys.executable, os.path.join(TOOLS, script)],
                            cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    print(result.stdout.strip())
    if result.returncode:
        print(result.stderr.strip())
        raise SystemExit("{} failed".format(script))


def package_files():
    yield "manifest.ini"
    yield "globalPlugins/superTools.py"
    themes = os.path.join(ROOT, "globalPlugins", "superToolsThemes")
    for name in sorted(os.listdir(themes)) if os.path.isdir(themes) else []:
        yield "globalPlugins/superToolsThemes/" + name
    for folder, _dirs, names in os.walk(os.path.join(ROOT, "doc")):
        for name in names:
            # readme.html is what NVDA opens; help.txt is what the Help screen
            # inside the add-on reads, and what the html was built from.
            if name in ("readme.html", "help.txt"):
                yield os.path.relpath(os.path.join(folder, name), ROOT).replace(os.sep, "/")
    for folder, _dirs, names in os.walk(os.path.join(ROOT, "locale")):
        for name in names:
            # The .po files are the sources translators work with; only the
            # compiled catalogues and the translated manifests are needed here.
            if name.endswith(".mo") or name in ("manifest.ini", "credits.json", "nvda.pot"):
                yield os.path.relpath(os.path.join(folder, name), ROOT).replace(os.sep, "/")


def main():
    run("make_doc.py")
    run("make_locale.py")
    run("check_locale.py")

    manifest = open(os.path.join(ROOT, "manifest.ini"), encoding="utf-8").read()
    version = re.search(r'version\s*=\s*"([^"]+)"', manifest).group(1)
    target = os.path.join(ROOT, "SuperTools-{}.nvda-addon".format(version))
    if os.path.exists(target):
        os.remove(target)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as package:
        for name in sorted(set(package_files())):
            path = os.path.join(ROOT, name.replace("/", os.sep))
            if not os.path.exists(path):
                raise SystemExit("missing: " + name)
            package.write(path, name)
    size = os.path.getsize(target) / 1024.0
    print("\nbuilt {} ({:.0f} KB, {} files)".format(
        os.path.basename(target), size, len(zipfile.ZipFile(target).namelist())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
