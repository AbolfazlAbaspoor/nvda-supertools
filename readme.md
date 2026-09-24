# SuperTools for NVDA

A toolbox for the [NVDA](https://www.nvaccess.org/) screen reader that keeps
growing. Today it repairs text typed with the wrong keyboard layout, gives
chosen words their own sound when NVDA speaks them, and manages running
processes — and it is built so that the next tool costs the user nothing.

Everything is reached from a single command mode, so the add-on occupies one
shortcut however much is added to it: no second shortcut to learn, nothing new
to collide with other add-ons. New tools are welcome; see
[Contributing](CONTRIBUTING.md).

Press **NVDA+Shift+U**, then one key:

| Key | What it does |
| --- | --- |
| `H` | Help, with every feature explained |
| `X` | The welcome / changes screen |
| `C` | Convert the selected text between two keyboard layouts |
| `Shift+C` | Convert the word before the cursor, without selecting it |
| `Z` | Undo the last conversion |
| `W` | Word Monitor: manage the words that get their own sound |
| `Shift+W` | Turn the Word Monitor on or off |
| `P` | Process Manager |
| `L` | Lock or unlock the keyboard |
| `T` | Check whether the clock is right |
| `U` | Look for a new version |
| `S` | Settings |
| `Escape` | Leave command mode |

While command mode is on, nothing reaches the program you are working in: no
command key is ever typed into your document. A key that is not a command only
plays a short beep and command mode stays on. If no key is pressed at all,
command mode ends by itself.

## Features

### Layout fixer

Works with every keyboard layout Windows has, not a pair you choose. The text
itself decides which layout it was typed with, and `C` moves it to the next one;
press `C` again to carry on around the ring. `sghl` becomes `سلام`, and `سلام`
becomes `sghl`, and with a third layout installed the next press takes it there.
Nothing has to be set up, and a layout can be left out in the settings.

It can also watch what you type and tell you when a word looks like it was typed
with the wrong layout — a Latin word without a single vowel — either with a short
sound or by converting it straight away.

The clipboard is used to replace the text, and its previous content is put back
afterwards.

### Word monitor

Words are kept in categories. A category holds the settings that words added to
it start from, and every word can keep those or use its own:

- match anywhere in the text or whole words only, and whether upper and lower
  case must match;
- what happens when the word is spoken: beeps only, extra text only, both, or
  not speaking the word at all;
- the text said before the word;
- the beeps: how many, how high, how long each one lasts, the gap between them,
  or a sequence of your own — or a sound file instead of the beeps.

The word list has a search box and shows how often each word has been heard.
Words can be imported from a text or JSON file or from the clipboard.

### Process manager

Name, PID and memory use in columns, with processor use and the publisher of
each program as two more columns that can be switched on. Filter by name, or
type a number to find a PID. End or restart the selected process, or every
process the filter shows — those two ask first. Open the file location, copy the
details, open the properties window, change the priority.

Restarted processes are started detached from NVDA and keep running when NVDA
restarts or exits.

### Keyboard lock

`L` locks the keyboard and `L` unlocks it. While it is locked every key is
swallowed before it reaches anything, NVDA included; the only key that still
works is the one that opens command mode, so pressing that and then `L` always
gets you out. A lock is never written to disk, so restarting NVDA ends it - the
last way out if anything goes wrong.

A locked keyboard is silent: a beep per key, at the speed a held key repeats,
would drown out everything and say nothing. It is said in words instead, and
only after the keyboard has been left alone for a while. Num Lock, Caps Lock
and Scroll Lock are put back the way they were when it unlocks, because Windows
flips those even when the press reaches nothing.

### Clock

`T` says how far the computer's clock is from the real time and offers to put it
right. A wrong clock breaks every secure connection while the errors talk about
certificates and never about the time, which is why it is worth being able to
check in a second. The time is read from the `Date` header any web server sends
back, so nothing is signed up for and nothing about the user is sent; a plain
`http` address is tried as well, because a badly wrong clock stops `https` from
working at all. Fixing it is either the Windows time service doing its job or
the clock set straight from that header, and Windows asks for permission before
either.

### Everywhere

Every feature can be switched off, or limited to certain applications and kept
out of others. All settings can be exported and imported, and a weekly backup is
kept automatically.

### Sounds

Every sound the add-on makes can come from a theme: for each sound separately,
either beeps or a sound file. `wav` plays through NVDA's own audio, `mp3` and
the other formats Windows can decode work as well, and whatever a theme leaves
out keeps the built-in beep — so a theme can be as small as a single sound.

How the beeps themselves are produced is a choice: built in, where a sequence is
made as one piece of sound so the gaps are exact, or NVDA's own beep, which
sounds like the rest of NVDA. Volume, and the short silence that keeps a first
beep from being swallowed, are settings as well.

Themes are JSON files in `globalPlugins/superToolsThemes/`, or in
`superToolsThemes/` inside the NVDA configuration folder for your own. Settings,
General tab, Sounds has a template to start from and opens that folder for you.
The author's name travels with the theme and is shown beside it.

### Making a language or a theme without leaving NVDA

Settings, General tab has a wizard for each. The language wizard walks through
every text, shows how far you are, saves the same `.po` file a translator would
send, and can show you your own language straight away without restarting NVDA
in it. The theme wizard builds a theme sound by sound, each one either beeps you
dial in or a sound file, with a Test button beside it.

### Nothing to set up by hand

The first run asks three questions — which tools you want, which two keyboard
layouts you switch between, how it should sound — and that is the whole setup.
Applications for a rule are ticked off the list of programs running now, sounds
are dialled in and tested with a button beside them, and a language or a sound
theme is written in a wizard. Nothing in SuperTools needs a text editor.

## Installing

Download the `.nvda-addon` file from the
[latest release](https://github.com/AbolfazlAbaspoor/nvda-supertools/releases)
and open it, or install it from NVDA's Add-on Store. NVDA 2024.1 or newer.

## Building from source

Python 3 and nothing else:

```
python tools/build.py
```

It regenerates the documentation and the translation catalogues, checks them,
and writes `SuperTools-<version>.nvda-addon`.

| Tool | What it does |
| --- | --- |
| `tools/build.py` | Builds the add-on package |
| `tools/make_locale.py` | Extracts `locale/nvda.pot` and compiles every `.po` to `.mo` |
| `tools/check_locale.py` | Checks the translations for missing texts and broken placeholders |
| `tools/make_doc.py` | Writes `doc/en/readme.html` from the help text in the add-on |
| `tests/test_supertools.py` | The test suite: `python tests/test_supertools.py` |
| `tools/release.py` | Publishes a version and fills in the store submission form |

## Releasing a version

```
python tools/release.py --open
```

One command does the whole round: it checks everything the Add-on Store
validates (the name, the shape of the version, that every address is https,
that `minimumNVDAVersion` and `lastTestedNVDAVersion` are NVDA versions the
store knows), builds the package, creates the GitHub release, uploads the
`.nvda-addon` to it, downloads it back to prove the address the store will
use really serves the file we built, and then prints the submission form
with every field already filled in. `--open` opens that form in a browser;
`--dry-run` changes nothing; `--form-only` skips straight to the form when
the release is already published.

Submitting an update is the same short form every time - a download address,
the source address, the publisher, the channel and the licence. The store
reads the version, the description, the translations and the checksum out of
the file itself. Only the first submission of an add-on waits for a person to
approve the publisher, which can take up to two weeks; after that the checks
are automatic and an update is usually in the store the same day.

To release, raise `version` in `manifest.ini` and `addon_version` in
`buildVars.py`, add what changed to the changelog above and to `VERSION_NOTES`
in the add-on, commit, then run the command. The token comes from `GITHUB_TOKEN`
or from the credentials git already pushes with.

## Translating

The help is translated too: it is `doc/<language>/help.txt`, plain text, and the
documentation NVDA shows is built from it by `tools/make_doc.py`. Persian is
included; another language is a new file in the same shape.

SuperTools speaks the language NVDA itself is set to. It comes with English,
Persian, Arabic, German, Spanish, French, Italian, Portuguese, Russian, Turkish
and Simplified Chinese.

To add a language, translate `locale/nvda.pot` with a tool such as
[Poedit](https://poedit.net/), save it as
`locale/<language>/LC_MESSAGES/nvda.po` and open a pull request — or just send
the file. Run `python tools/make_locale.py` to compile it.

Put your name in the `Last-Translator` field: it is collected into
[TRANSLATORS.md](TRANSLATORS.md) and shown in the add-on's settings beside the
language you translated. A language can be the work of several people — the
field takes a list separated by commas, and the wizard inside the add-on adds a
name rather than replacing the ones already there.

The translations shipped today were made by an AI and have not been reviewed by
native speakers. Corrections are very welcome, and whoever makes them is
credited.

## Notes for add-on reviewers

A few decisions in this add-on look unusual at first glance, so here is why they
are the way they are, and what happens when they fail.

**One gesture only.** The add-on binds `NVDA+Shift+U` and nothing else.
Everything is reached from command mode, so it takes almost nothing from the
user's key space and cannot collide with other add-ons.

**Command mode uses `inputCore.manager._captureFunc`.** That is how the keys
pressed after `NVDA+Shift+U` are captured, the same mechanism NVDA's own input
help uses. The previous capture function is saved and put back when command mode
ends, in `terminate()`, and in the `except` path if anything goes wrong. If the
attribute ever disappears, command mode reports that it could not start and the
rest of the add-on keeps working. Modifier keys and non-keyboard gestures are
passed through untouched.

**`speech.speech.speak` is replaced while the Word Monitor is on.** There is no
public hook that can both add a sound to an utterance and leave the word out of
it, which is what the feature does. The original function is kept and restored
in `terminate()`; every failure inside the replacement falls back to calling the
original, so a bug there cannot silence NVDA. When the monitor is off, the call
goes straight through.

**`gui.settingsDialogs.SettingsDialog._instances` is read on one error path.**
NVDA refuses to open a settings dialog while an old instance is still alive, and
a dialog that was destroyed but not yet collected used to make the settings
impossible to open. The add-on only touches that table after catching
`MultiInstanceError`: it collects garbage, drops the destroyed entries and tries
once more. Everything is inside `try`/`except`, and a failure just reports that
the settings could not be opened.

**The process list comes from `NtQuerySystemInformation`.** One call returns
every process with its name, memory and processor time. Measured on a machine
with 156 processes: 2.8 ms, against 416 ms for asking psutil process by process,
which is too slow for a list that refreshes itself. psutil and then `tasklist`
are used as fallbacks if the call ever fails, and psutil is optional — the
add-on works without it.

**Restarted processes are started detached.**
`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB`, with
no inherited handles, so a program restarted from the Process Manager does not
die with NVDA. If a job object forbids breakaway, the flag is dropped and the
launch is retried.

**Nothing destructive happens by accident.** Ending or restarting every filtered
process needs a non-empty filter and asks for confirmation first, so no action
can run over the whole machine.

**Beeps are generated, not played one at a time.** `tones.beep()` stops the
player before each tone, so a sequence built from repeated calls drifts and can
overlap. The add-on builds the whole sequence, silences included, into one
buffer and feeds it to a `WavePlayer` of its own; if that fails for any reason
it falls back to `tones.beep()`.

**Where data is written.** Only inside the NVDA configuration folder:
`superTools.json` for the word lists, beeps and counters, and
`superToolsBackups/` for the weekly backup (five kept). Plain options live in
`nvda.ini` as usual. Structured data cannot live in `nvda.ini` — configobj
writes nested lists back as broken strings — which is why the JSON file exists.

**The clipboard** is used to replace text when converting, and its previous
content is put back afterwards by default.

**Typed characters** are seen through `event_typedCharacter`, only when the
"watch for words typed with the wrong layout" option is switched on. The work per
character is appending to a small string; the check runs when a word ends.

**The only network access is the update check, and it is off by default.** When
switched on it reads the releases list of this repository, at most once a day,
compares the version number and says whether a newer one exists. It sends
nothing about the user, and downloads and installs nothing: the most it does is
open the release page in the browser if the user says yes. There is also a
"Check now" button, which is the only thing that touches the network while the
setting is off. No telemetry, no bundled binaries, no non-free dependencies.

**Translations** are ordinary gettext catalogues. `tools/make_locale.py`
extracts `locale/nvda.pot` and compiles each `.po` with a small pure-Python
writer, so no gettext installation is needed to build; `tools/check_locale.py`
fails the build on a missing text, a broken placeholder or a lost `&`. The `.pot`
is committed, so the usual community translation workflow can be used.

## Changelog

### 1.0.1

- A locked keyboard is silent, and says in words - now and then, not for every
  key - that it is locked.
- Num Lock, Caps Lock and Scroll Lock are put back the way they were when the
  keyboard is unlocked.
- A key that is not a command cannot pile its beeps up when it is held down.

### 1.0.0

The first public release. Everything described above is in it: the layout
fixer, the word monitor, the process manager, the sound themes, the wizards
for a language or a theme, and the command mode they all live behind.

## Credits

SuperTools is written by Abolfazl Abaspoor, with the help of an AI assistant.
Translations and sound themes carry their own authors' names, in
[TRANSLATORS.md](TRANSLATORS.md) and in the add-on's settings.

## Licence

GNU General Public License version 2. See [LICENSE](LICENSE).
