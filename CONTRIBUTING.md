# Contributing to SuperTools

SuperTools is meant to grow. A new tool, a new language, a fix, a better way of
doing something that is already there — all of it is welcome.

One thing to know before you start: **nobody pushes to this repository
directly.** Every change, including the ones from the author, arrives as a pull
request and is merged only after review. Releases are cut by the maintainer
only. That is not distrust; it is what keeps a screen reader add-on safe to
install, because a mistake here does not annoy a user, it can leave them unable
to use their computer.

## How to propose a change

1. **Fork** the repository and create a branch for your change.
2. Make the change. Keep it to one subject per pull request — a tool, a fix, a
   language — so it can be reviewed properly.
3. Run the checks:
   ```
   python tools/make_locale.py
   python tools/check_locale.py
   python tests/test_supertools.py
   python tools/build.py
   ```
   The tests must all pass, `check_locale.py` must report no broken placeholders,
   and the build must succeed. The same three run automatically on your pull
   request, on Windows, so you will see the result there as well.
4. Test it in NVDA. Install the package the build produced, restart NVDA, and
   use what you changed.
5. Open a **pull request** describing what it does, why, and what you tested it
   on (which NVDA version, which Windows version).

The maintainer reviews it, asks questions if needed, and merges it when it is
ready. If it is not merged, you will be told why.

## Adding a new tool

The design rule is the one in the readme: **the add-on takes one shortcut.** A
new tool becomes a key in command mode, not a new gesture. Concretely:

- add the key and the method to `_commandActions()`;
- give it a beep sequence in `COMMAND_SOUND_DEFAULTS` and a label in
  `COMMAND_SOUND_ITEMS`, so the user can tell by ear which command ran;
- give it a tab, or a section on an existing tab, in the settings dialog, and
  let it be switched off;
- add a test to `tests/test_supertools.py` for whatever can be tested without a
  window: the suite runs the add-on with NVDA and wxPython replaced by
  stand-ins, so logic, files and speed are all reachable;
- if it is something that runs while NVDA speaks or while the user types, say
  in the pull request what it costs per event. The speech path is measured in
  fractions of a millisecond and should stay that way.

## Adding a language

You do not need to touch any code:

1. Translate `locale/nvda.pot` with a tool such as [Poedit](https://poedit.net/).
2. Save it as `locale/<language>/LC_MESSAGES/nvda.po`.
3. Optionally add `locale/<language>/manifest.ini` with a translated `summary`
   and `description`.
4. Run `python tools/make_locale.py`, then `python tools/check_locale.py`.
5. Open a pull request, or simply send the `.po` file to the author.

Keep the placeholders — `{name}`, `{n}`, `{text}`, `{e}` — exactly as they are,
and keep the `&` that marks a keyboard shortcut in a button label.

## Adding a sound theme

A theme needs no code either. Settings, General tab, Sounds, **Save a theme
template...** gives you a JSON file with every sound the add-on makes. For each
one, keep the beeps, change them, or point at a sound file next to the JSON:

```json
"start": {"file": "start.wav"},
"escape": {"beeps": [[392, 70], [262, 90]], "gap": 20}
```

`wav` plays through NVDA's own audio and is the safest choice; `mp3` and the
other formats Windows can decode also work. Remove any sound you do not want to
change — what a theme leaves out keeps the built-in beep.

Put your name in `author`: it is shown beside the theme in the settings. Send
the theme as a pull request adding it to `globalPlugins/superToolsThemes/`,
together with its sound files if it has any. Keep the files small and free to
redistribute under GPL v2; say where they came from in the pull request.

## Style

Follow what the file already does. In short: English comments that say *why*
rather than *what*, no dead code, every user-visible string inside `_()`, no
new dependency outside the Python standard library and NVDA's own API, and
everything that touches NVDA internals wrapped so that a failure degrades one
feature instead of breaking NVDA.

## Licence

SuperTools is under the GNU General Public License version 2. By opening a pull
request you agree that your contribution is released under the same licence.
