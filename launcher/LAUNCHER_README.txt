wot-0.9.22-offline-battles v1.0.0

Supported client: Chinese HD World of Tanks 0.9.22.0.1 #1513 (32-bit).
The launcher and bundled server require 64-bit Windows.

Extract the complete ZIP into a new empty folder. Keep _internal and licenses
beside wot-0.9.22-offline-battles.exe, run the launcher and select the game.
Use the existing save and vehicle profile. An update does not require resetting
saves, recordings or settings. Do not mix old and new launcher files or install
another mod copy manually; the launcher installs its matching client payload.

The route toolbar groups creation, copy/delete and undo/redo on its first row;
main/reserve, map checks, view and background-image import are on the second.
Restore contains the existing Reset route and Restore default routes commands.
These remain unavailable for the read-only Default profile.
Artillery deployment and relocation use automatic navigation. Endgame and
empty-ammunition sorties use the authored attack route and may borrow valid
ordinary main/reserve roads when necessary. Deployment does not consume ordinary
road capacity; borrowed sortie roads count their actual occupancy.

All LAN participants must update together and restart the room/server. A room
explicitly hosted by the launcher remains open until Stop room or launcher exit;
leaving one player client does not terminate the other players' room.

Closing the visible single-player game also closes its hidden simulation worker
and temporary server. Cleanup normally takes a few seconds and may wait longer
while a recording finishes. The launcher itself stays open.

Set replay recording to Off, Last or All in the game. Recordings are saved under
replays/offline in the game folder. Open .wotlanreplay files from the launcher's
Replay tab. Playback is forward 1x with a manual camera; pause, seeking, speed
controls and native .wotreplay export are not available. Retain the recording's
original vehicle profile. Playback does not award battle rewards.

Maintenance (Repair tab)
------------------------
Four equally spaced, normal-height buttons use a two-by-two layout. Resizing
the window does not stretch their height. Explanations below the buttons wrap
with the available width and follow the selected interface language. Every action requires
confirmation, with No selected by default. Close the game, worker, LAN room
and other offline launcher windows first. Repair mod installation reinstalls the files bundled with this launcher;
it does not download a newer version and keeps usable saved data and profiles.
Reset all offline client settings resets graphics, sound, input and account
settings in playerprefs.xml / workerprefs.xml and older isolated profiles,
without resetting saves or touching
the normal client profile. Clear all offline saves deletes every offline save,
including legacy copies and pending grants, then creates a fresh fully unlocked
default save; tactics, vehicle profiles and client preferences are preserved.
Delete all data and restore factory defaults removes project-owned external and
game-folder data, profiles, routes, lineups, settings, caches, recordings, logs,
reports and interrupted recovery data, restores owned vehicle overlays, then
reinstalls this launcher's bundled mod and rebuilds defaults. Shared offline
data affects other launcher packages. Manually copied reports, downloaded
packages, stock game resources and other mods are not searched or deleted.
The launcher closes after factory reset to prevent stale in-memory settings
from being saved again. Reopen it before using the reset installation. A failed
reset reports the failing operation and never reports factory success.

Replay preflight uses the same 8-GiB cumulative decompressed bound as recording
and playback. Data is streamed; the 2-MiB record limit, footer/count and gzip
integrity checks still apply. Compressed file size is not the replay size bound.

Use the launcher's built-in vehicle editor and error-report controls. The player
download includes START_DIAGNOSTIC_TEST.bat for detailed gameplay diagnostics,
and START_SPIKE_PROFILE.bat for optional detailed profiling. The normal EXE
uses small key-event logs. Detailed geometry logs are limited to 2 MiB/minute
and 32 MiB per client process, with explicit suppression notices. Exhausted
budgets skip further JSON encoding; motion histories also skip construction
until the budget reopens. Test captures split rotation catalog/native costs
without changing collision queries. Errors and
lifecycle messages remain enabled after the diagnostic budget is exhausted.

Normal battles use wot-0.9.22-offline-battles.exe. START_ROOF_CRUSH_TEST.bat
and START_ROOF_SHOT_DROP_TEST.bat are separate opt-in bridge-drop fixtures.
Exit both the game and launcher before switching entrances. The fixtures do
not change saved room presets; the contact fixes also apply in normal battles.

Customize save -> Coatings edits preset-style inventory, including hidden styles.
Customize save -> Members adds 100% recruits by nation, role, gender, complete
skill count and trained vehicle. Skills remain unassigned for the client to
choose; zero gives no secondary-skill XP. Close the game before adding. The next
startup delivers each recruit to this save's barracks with a system notice.
Full barracks leave requests pending. Saved retry identities prevent duplicate
delivery after an interrupted inbox cleanup. The Members tab follows Coatings.
Bot tactics also has an independent outfit checkbox below consumables: inherit,
enable or disable the existing seasonal rented styles, keeping locked-outfit
exceptions. It does not select a style or add a battle-count expiry.
Select one vehicle or all compatible vehicles, add copies or fill missing styles,
then Save with the game closed. One rental copy grants its original battle count.
Fully unlocked saves receive one copy per compatible vehicle on their first style
stock initialization, including existing saves; later use/sales are not replenished.

English release notes:
https://github.com/colorfulmeans/wot-0.9.22-offline-battles/releases/tag/v1.0.0

This mod is free; resale is prohibited. World of Tanks game assets are not
included. This unofficial project is not endorsed by Wargaming.
See LICENSE, THIRD_PARTY_NOTICES.md and licenses for license terms. The optional
crash recorder downloads Microsoft ProcDump only with the launcher's consent
setting. The bundled replay runtime is CPython 3.11.9 from python.org.

Configuration updates
---------------------
Bot tactics Default is read-only in both tabs. Create a custom profile to edit.
Restore default draft resets that custom draft, including pending forms and
undo history, without applying it. Import/name conflicts receive numeric suffixes.
Independent development, equipment, ammunition, consumables and coupled crew
presets inherit from the existing scope hierarchy. Ammunition uses digit ratios;
all zero carries no ammunition. Magazine ratios count magazines, not rounds.
Stock development only allows no equipment, in the dropdown and validation.

Both room interfaces default to Random per-team vehicle types. Random shows
all five class icons checked and disabled, while preserving the manual mask.
Manual checks guarantee one BOT of each checked class and forbid unchecked
automatic types. Fixed launcher Bots remain and can satisfy a guarantee;
players never do. Shrinking drops newer selections first; growth restores none.
Manual artillery guarantees one BOT even below seven. Random mode retains its
0 / 0-1 / 0-2 / 0-3 limits at sizes 1-6 / 7-9 / 10-12 / 13-15. Impossible
SPG-only fills, missing classes or incompatible tier windows refuse start.

Members are selected by nation, tank type, vehicle, actual crew seat, gender,
training (50/75/100) and skill count. Seat limits include combined roles and
number duplicate professions separately. Women always have zero-XP Brothers
in Arms, counted in the total. Below 100% ordinary skills are disabled.
Full-skill choices are durable member-owned credits; choose skills in the
native client. Moving seats or restarting never renews credits. Recruits,
credits and delivery notices commit together to the selected save.

New unlocked saves mount three legal class-priority devices (improved first,
ordinary fallback within the same family) and the corresponding
battle directive, with directive auto-resupply checked. Users may change or
remove them; saved choices are never reapplied as defaults. Career saves remain
stock. The vehicle editor displays magazine/trigger reload intervals in seconds;
underlying old rate edits keep their native meaning. Trigger count is limited by
magazine capacity and the existing runtime limit (64), with within-trigger time
at most ten seconds. A partial trigger fires only real remaining rounds.
The open vehicle editor follows the main language selector, including numeric
limits and validation errors. Switching languages preserves filters, selected
fields, unsaved input and viewer position without reloading or saving the profile.

CPython 3.11.9 license
======================

The following text is the LICENSE file distributed with CPython 3.11.9.

A. HISTORY OF THE SOFTWARE
==========================

Python was created in the early 1990s by Guido van Rossum at Stichting
Mathematisch Centrum (CWI, see https://www.cwi.nl) in the Netherlands
as a successor of a language called ABC.  Guido remains Python's
principal author, although it includes many contributions from others.

In 1995, Guido continued his work on Python at the Corporation for
National Research Initiatives (CNRI, see https://www.cnri.reston.va.us)
in Reston, Virginia where he released several versions of the
software.

In May 2000, Guido and the Python core development team moved to
BeOpen.com to form the BeOpen PythonLabs team.  In October of the same
year, the PythonLabs team moved to Digital Creations, which became
Zope Corporation.  In 2001, the Python Software Foundation (PSF, see
https://www.python.org/psf/) was formed, a non-profit organization
created specifically to own Python-related Intellectual Property.
Zope Corporation was a sponsoring member of the PSF.

All Python releases are Open Source (see https://opensource.org for
the Open Source Definition).  Historically, most, but not all, Python
releases have also been GPL-compatible; the table below summarizes
the various releases.

    Release         Derived     Year        Owner       GPL-
                    from                                compatible? (1)

    0.9.0 thru 1.2              1991-1995   CWI         yes
    1.3 thru 1.5.2  1.2         1995-1999   CNRI        yes
    1.6             1.5.2       2000        CNRI        no
    2.0             1.6         2000        BeOpen.com  no
    1.6.1           1.6         2001        CNRI        yes (2)
    2.1             2.0+1.6.1   2001        PSF         no
    2.0.1           2.0+1.6.1   2001        PSF         yes
    2.1.1           2.1+2.0.1   2001        PSF         yes
    2.1.2           2.1.1       2002        PSF         yes
    2.1.3           2.1.2       2002        PSF         yes
    2.2 and above   2.1.1       2001-now    PSF         yes

Footnotes:

(1) GPL-compatible doesn't mean that we're distributing Python under
    the GPL.  All Python licenses, unlike the GPL, let you distribute
    a modified version without making your changes open source.  The
    GPL-compatible licenses make it possible to combine Python with
    other software that is released under the GPL; the others don't.

(2) According to Richard Stallman, 1.6.1 is not GPL-compatible,
    because its license has a choice of law clause.  According to
    CNRI, however, Stallman's lawyer has told CNRI's lawyer that 1.6.1
    is "not incompatible" with the GPL.

Thanks to the many outside volunteers who have worked under Guido's
direction to make these releases possible.


B. TERMS AND CONDITIONS FOR ACCESSING OR OTHERWISE USING PYTHON
===============================================================

Python software and documentation are licensed under the
Python Software Foundation License Version 2.

Starting with Python 3.8.6, examples, recipes, and other code in
the documentation are dual licensed under the PSF License Version 2
and the Zero-Clause BSD license.

Some software incorporated into Python is under different licenses.
The licenses are listed with code falling under that license.


PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2
--------------------------------------------

1. This LICENSE AGREEMENT is between the Python Software Foundation
("PSF"), and the Individual or Organization ("Licensee") accessing and
otherwise using this software ("Python") in source or binary form and
its associated documentation.

2. Subject to the terms and conditions of this License Agreement, PSF hereby
grants Licensee a nonexclusive, royalty-free, world-wide license to reproduce,
analyze, test, perform and/or display publicly, prepare derivative works,
distribute, and otherwise use Python alone or in any derivative version,
provided, however, that PSF's License Agreement and PSF's notice of copyright,
i.e., "Copyright (c) 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010,
2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023 Python Software Foundation;
All Rights Reserved" are retained in Python alone or in any derivative version
prepared by Licensee.

3. In the event Licensee prepares a derivative work that is based on
or incorporates Python or any part thereof, and wants to make
the derivative work available to others as provided herein, then
Licensee hereby agrees to include in any such work a brief summary of
the changes made to Python.

4. PSF is making Python available to Licensee on an "AS IS"
basis.  PSF MAKES NO REPRESENTATIONS OR WARRANTIES, EXPRESS OR
IMPLIED.  BY WAY OF EXAMPLE, BUT NOT LIMITATION, PSF MAKES NO AND
DISCLAIMS ANY REPRESENTATION OR WARRANTY OF MERCHANTABILITY OR FITNESS
FOR ANY PARTICULAR PURPOSE OR THAT THE USE OF PYTHON WILL NOT
INFRINGE ANY THIRD PARTY RIGHTS.

5. PSF SHALL NOT BE LIABLE TO LICENSEE OR ANY OTHER USERS OF PYTHON
FOR ANY INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES OR LOSS AS
A RESULT OF MODIFYING, DISTRIBUTING, OR OTHERWISE USING PYTHON,
OR ANY DERIVATIVE THEREOF, EVEN IF ADVISED OF THE POSSIBILITY THEREOF.

6. This License Agreement will automatically terminate upon a material
breach of its terms and conditions.

7. Nothing in this License Agreement shall be deemed to create any
relationship of agency, partnership, or joint venture between PSF and
Licensee.  This License Agreement does not grant permission to use PSF
trademarks or trade name in a trademark sense to endorse or promote
products or services of Licensee, or any third party.

8. By copying, installing or otherwise using Python, Licensee
agrees to be bound by the terms and conditions of this License
Agreement.


BEOPEN.COM LICENSE AGREEMENT FOR PYTHON 2.0
-------------------------------------------

BEOPEN PYTHON OPEN SOURCE LICENSE AGREEMENT VERSION 1

1. This LICENSE AGREEMENT is between BeOpen.com ("BeOpen"), having an
office at 160 Saratoga Avenue, Santa Clara, CA 95051, and the
Individual or Organization ("Licensee") accessing and otherwise using
this software in source or binary form and its associated
documentation ("the Software").

2. Subject to the terms and conditions of this BeOpen Python License
Agreement, BeOpen hereby grants Licensee a non-exclusive,
royalty-free, world-wide license to reproduce, analyze, test, perform
and/or display publicly, prepare derivative works, distribute, and
otherwise use the Software alone or in any derivative version,
provided, however, that the BeOpen Python License is retained in the
Software, alone or in any derivative version prepared by Licensee.

3. BeOpen is making the Software available to Licensee on an "AS IS"
basis.  BEOPEN MAKES NO REPRESENTATIONS OR WARRANTIES, EXPRESS OR
IMPLIED.  BY WAY OF EXAMPLE, BUT NOT LIMITATION, BEOPEN MAKES NO AND
DISCLAIMS ANY REPRESENTATION OR WARRANTY OF MERCHANTABILITY OR FITNESS
FOR ANY PARTICULAR PURPOSE OR THAT THE USE OF THE SOFTWARE WILL NOT
INFRINGE ANY THIRD PARTY RIGHTS.

4. BEOPEN SHALL NOT BE LIABLE TO LICENSEE OR ANY OTHER USERS OF THE
SOFTWARE FOR ANY INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES OR LOSS
AS A RESULT OF USING, MODIFYING OR DISTRIBUTING THE SOFTWARE, OR ANY
DERIVATIVE THEREOF, EVEN IF ADVISED OF THE POSSIBILITY THEREOF.

5. This License Agreement will automatically terminate upon a material
breach of its terms and conditions.

6. This License Agreement shall be governed by and interpreted in all
respects by the law of the State of California, excluding conflict of
law provisions.  Nothing in this License Agreement shall be deemed to
create any relationship of agency, partnership, or joint venture
between BeOpen and Licensee.  This License Agreement does not grant
permission to use BeOpen trademarks or trade names in a trademark
sense to endorse or promote products or services of Licensee, or any
third party.  As an exception, the "BeOpen Python" logos available at
http://www.pythonlabs.com/logos.html may be used according to the
permissions granted on that web page.

7. By copying, installing or otherwise using the software, Licensee
agrees to be bound by the terms and conditions of this License
Agreement.


CNRI LICENSE AGREEMENT FOR PYTHON 1.6.1
---------------------------------------

1. This LICENSE AGREEMENT is between the Corporation for National
Research Initiatives, having an office at 1895 Preston White Drive,
Reston, VA 20191 ("CNRI"), and the Individual or Organization
("Licensee") accessing and otherwise using Python 1.6.1 software in
source or binary form and its associated documentation.

2. Subject to the terms and conditions of this License Agreement, CNRI
hereby grants Licensee a nonexclusive, royalty-free, world-wide
license to reproduce, analyze, test, perform and/or display publicly,
prepare derivative works, distribute, and otherwise use Python 1.6.1
alone or in any derivative version, provided, however, that CNRI's
License Agreement and CNRI's notice of copyright, i.e., "Copyright (c)
1995-2001 Corporation for National Research Initiatives; All Rights
Reserved" are retained in Python 1.6.1 alone or in any derivative
version prepared by Licensee.  Alternately, in lieu of CNRI's License
Agreement, Licensee may substitute the following text (omitting the
quotes): "Python 1.6.1 is made available subject to the terms and
conditions in CNRI's License Agreement.  This Agreement together with
Python 1.6.1 may be located on the internet using the following
unique, persistent identifier (known as a handle): 1895.22/1013.  This
Agreement may also be obtained from a proxy server on the internet
using the following URL: http://hdl.handle.net/1895.22/1013".

3. In the event Licensee prepares a derivative work that is based on
or incorporates Python 1.6.1 or any part thereof, and wants to make
the derivative work available to others as provided herein, then
Licensee hereby agrees to include in any such work a brief summary of
the changes made to Python 1.6.1.

4. CNRI is making Python 1.6.1 available to Licensee on an "AS IS"
basis.  CNRI MAKES NO REPRESENTATIONS OR WARRANTIES, EXPRESS OR
IMPLIED.  BY WAY OF EXAMPLE, BUT NOT LIMITATION, CNRI MAKES NO AND
DISCLAIMS ANY REPRESENTATION OR WARRANTY OF MERCHANTABILITY OR FITNESS
FOR ANY PARTICULAR PURPOSE OR THAT THE USE OF PYTHON 1.6.1 WILL NOT
INFRINGE ANY THIRD PARTY RIGHTS.

5. CNRI SHALL NOT BE LIABLE TO LICENSEE OR ANY OTHER USERS OF PYTHON
1.6.1 FOR ANY INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES OR LOSS AS
A RESULT OF MODIFYING, DISTRIBUTING, OR OTHERWISE USING PYTHON 1.6.1,
OR ANY DERIVATIVE THEREOF, EVEN IF ADVISED OF THE POSSIBILITY THEREOF.

6. This License Agreement will automatically terminate upon a material
breach of its terms and conditions.

7. This License Agreement shall be governed by the federal
intellectual property law of the United States, including without
limitation the federal copyright law, and, to the extent such
U.S. federal law does not apply, by the law of the Commonwealth of
Virginia, excluding Virginia's conflict of law provisions.
Notwithstanding the foregoing, with regard to derivative works based
on Python 1.6.1 that incorporate non-separable material that was
previously distributed under the GNU General Public License (GPL), the
law of the Commonwealth of Virginia shall govern this License
Agreement only as to issues arising under or with respect to
Paragraphs 4, 5, and 7 of this License Agreement.  Nothing in this
License Agreement shall be deemed to create any relationship of
agency, partnership, or joint venture between CNRI and Licensee.  This
License Agreement does not grant permission to use CNRI trademarks or
trade name in a trademark sense to endorse or promote products or
services of Licensee, or any third party.

8. By clicking on the "ACCEPT" button where indicated, or by copying,
installing or otherwise using Python 1.6.1, Licensee agrees to be
bound by the terms and conditions of this License Agreement.

        ACCEPT


CWI LICENSE AGREEMENT FOR PYTHON 0.9.0 THROUGH 1.2
--------------------------------------------------

Copyright (c) 1991 - 1995, Stichting Mathematisch Centrum Amsterdam,
The Netherlands.  All rights reserved.

Permission to use, copy, modify, and distribute this software and its
documentation for any purpose and without fee is hereby granted,
provided that the above copyright notice appear in all copies and that
both that copyright notice and this permission notice appear in
supporting documentation, and that the name of Stichting Mathematisch
Centrum or CWI not be used in advertising or publicity pertaining to
distribution of the software without specific, written prior
permission.

STICHTING MATHEMATISCH CENTRUM DISCLAIMS ALL WARRANTIES WITH REGARD TO
THIS SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS, IN NO EVENT SHALL STICHTING MATHEMATISCH CENTRUM BE LIABLE
FOR ANY SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT
OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

ZERO-CLAUSE BSD LICENSE FOR CODE IN THE PYTHON DOCUMENTATION
----------------------------------------------------------------------

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.

Female recruits use native passport name/icon groups matching their gender.
Previously pending female requests retry automatically; do not add duplicates.

Effective settings preview is a read-only table of settings, values and rule
sources. It includes rules already added to the current draft, not unsubmitted
form fields. All selected scopes are resolved; inherited difficulty retains
room rating sampling. Opening this window does not save or apply the profile.

The current default-seed revision replaces obsolete Default progress and old
Default backups once, without keeping a backup or importing legacy progress.
Completion is marked only after replacement succeeds. Later edits are kept on
subsequent starts and repairs. Other named saves are preserved.

Saves -> Initialize save requires a closed game and confirmation. Default is
replaced with the current fully unlocked seed without a backup. For named
saves, name, type and earnings multiplier are kept; progress and pending rewards
return to new-save defaults. A ZIP backup is kept in its pre-initialize recovery
folder and can be selected with Restore save.

Member recruitment uses the same standard, loadable vehicle filter as player
vehicles, including supported retired vehicles. Garage and Members share full
nation captions in this display order: China, USSR, USA, Germany, Czech,
France, UK, Japan, Poland, Sweden. This never changes native nation IDs.

Members shows total berths, current barracks occupants, undelivered pending
recruits and remaining recruit capacity. Crew already serving in vehicles and
dismissed crew do not occupy barracks berths. Add 16 barracks berths grants one
free block to the selected save; it requires the game to be closed. Existing
client purchases retain their normal price. Pending recruits reserve space,
excluding requests whose durable delivery receipt already exists. A full
barracks refuses new recruits with a warning; old pending requests are kept.
Initial berth grants survive the first game startup, backup and restore.
Initialize save returns capacity to the save type's original default.
