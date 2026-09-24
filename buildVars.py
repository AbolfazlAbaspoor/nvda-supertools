# -*- coding: UTF-8 -*-
"""
Build variables in the shape the official NVDA add-on template expects, so the
add-on can also be built with SCons alongside tools/build.py.
"""

def _(text):
    return text

addon_info = {
    "addon_name": "superTools",
    "addon_summary": _("SuperTools"),
    "addon_description": _(
        "A toolbox for NVDA that keeps growing. It repairs text typed with the wrong "
        "keyboard layout, gives chosen words their own sound when NVDA speaks them, and "
        "manages running processes. Everything is reached from a single command mode "
        "(NVDA+Shift+U), so the add-on occupies one shortcut however much is added to it."),
    "addon_version": "1.0.0",
    "addon_author": "Abolfazl Abaspoor <abbasporaboalfazl@gmail.com>",
    "addon_url": "https://github.com/AbolfazlAbaspoor/nvda-supertools",
    "addon_docFileName": "readme.html",
    "addon_minimumNVDAVersion": "2024.1",
    "addon_lastTestedNVDAVersion": "2026.2.0",
    "addon_updateChannel": None,
    "addon_license": "GPL v2",
    "addon_licenseURL": "https://www.gnu.org/licenses/old-licenses/gpl-2.0.html",
}

# Source files that carry translatable text.
pythonSources = ["globalPlugins/superTools.py"]

# Files to include as they are.
i18nSources = pythonSources + ["buildVars.py"]

# Files that must not end up in the package.
excludedFiles = []

# The languages the documentation is available in.
baseLanguage = "en"

markdownExtensions = []
brailleTables = {}
symbolDictionaries = {}
