wot-0.9.22-offline-battles
================================

The launcher prepares one battle before the game starts. It installs the mod,
starts the required local server and hidden simulation client for World of
Tanks, and stops that server when the game closes. Its bundled client and
server payloads are only for the exact #1513 client described below; it does
not install or start earlier client lines.

1. Extract the downloaded ZIP once, then start wot-0.9.22-offline-battles.exe
   from the extracted folder. Keep the folder
   together; the launcher needs the files beside it.
2. Select your World of Tanks folder. The list holds the folders you used
   before. Browse can add another folder.
3. Pick a mode:
   - Single player: choose the save, player name, Bot lineup, vehicle data
     profile and team settings you want, then press Start single-player battle.
     The launcher owns the private server and hidden simulation client for that
     session.
   - Online: the host starts a LAN room, then joins it. Other players enter the
     host address and join the same room. Everyone should use the same build.
4. The lower tabs manage saves, vehicle data, exact Bot lineups and repair
   operations. Close the game before editing persistent state.

Supported client
================

The bundled mod is for the Chinese HD Windows client:

    World of Tanks 0.9.22.0.1 #1513

The launcher identifies that client from version.xml (and the installed mod as
an explicit fallback). Other client versions are refused rather than treated
as compatible.

Saves
=====

Each save has an independent garage, balances, account settings and battle
history. You can create, rename, delete, back up and restore saves from the
launcher. A save backup is a ZIP containing that save only.

The selected save is passed to the game when it starts. Do not edit, restore or
delete a save while a game client is running because the game owns those files
for the duration of the session.

Vehicle data and Bot lineups
============================

Vehicle data profiles can override supported vehicle values. A LAN room pins
its chosen profile when the room starts; joiners receive the room's vehicle
data automatically for the session.

Bot lineup profiles can pin vehicles and Bot skill tiers to team slots. Exact
lineups require a launcher-owned server so the room and all clients share the
same configuration.

Crash reports
=============

Crash collection is optional. When enabled for the supported client, the
launcher can collect logs and crash evidence into a report ZIP. The report
button can also package the latest session manually.

Full-memory dump collection is a separate opt-in because those dump files can
be very large. The launcher downloads Microsoft's ProcDump only after consent
and validates the expected executable before using it.

Repair
======

The repair tab can reinstall the bundled mod, restore known launcher-owned
state, or reset the offline state after confirmation. It is deliberately
conservative about third-party files and refuses unsafe redirected paths.

LAN notes
=========

The server listens on TCP port 28782. The host may need to allow the packaged
server executable through Windows Firewall. The launcher tests the actual
application protocol, not just whether a TCP port is open.

If the hosted server never opens port 28782, another server may already use
that port. Close it and start the game again.

License, source, and bundled runtimes
=====================================

This launcher is part of wot-0.9.22-offline-battles and is distributed under
GNU GPL version 3, without warranty. LICENSE and THIRD_PARTY_NOTICES.md are
included beside this file. The corresponding source is available at:

https://github.com/colorfulmeans/wot-0.9.22-offline-battles
