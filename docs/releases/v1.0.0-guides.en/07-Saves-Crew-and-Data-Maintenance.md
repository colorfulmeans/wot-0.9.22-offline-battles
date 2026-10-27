# Saves, Crew and Data Maintenance

Version: 1.0.0. Supported client: Chinese HD World of Tanks 0.9.22.0.1 #1513.

## 1. What belongs to a save

Each save owns its garage, crew, account state and battle records. New saves offer fully unlocked or new-account/career modes. Game startup uses the selected save.

Room connections, vehicle attribute profiles, Bot lineups and tactical profiles are separately managed. Switching a save does not automatically switch all those settings, and a save backup is not a complete backup of every shared modification and route.

Unlocked defaults provide full-skill crew, legal improved equipment, matching directives and directive resupply. Later saved choices remain. Career saves keep their new-account defaults.

## 2. Save actions

- New save creates an independent named save in the selected mode.
- Rename changes its display name without merging another save.
- Delete removes the selected save after confirmation.
- Open save folder shows actual files.
- Backup exports a ZIP.
- Restore selects an existing backup ZIP, hence the file picker. It is not an automatic undo of the previous battle.
- Initialize resets the selected save to its original creation mode after confirmation.

Close the game before edits, initialization or backup/restore so runtime state does not overwrite disk changes. Read the restore confirmation's actual replacement scope.

## 3. Crew editor

Open Saves → Customize save → Members.

1. Choose nation, class and an available real vehicle.
2. Choose an actual seat; combined roles are shown and duplicate professions are numbered separately.
3. Choose gender, 50/75/100% training, and skill/perk count.
4. Check capacity and Add to barracks.
5. Receive the recruit in that save on next game startup, with a system notice.

The cap includes the seat's combined roles, counting shared skills once. Choose actual skills in the client after 100% training; the launcher does not prescribe their order. Below 100%, ordinary skill credit is unavailable.

Female recruits always have zero-XP Brothers in Arms, counted in the selected total, with appropriate identity data. Credits belong to the member; moving seats, changing vehicle or restarting does not grant another set.

Requests are persisted for the selected save. Interrupted delivery can retry without duplicating recruits. Full barracks retain pending requests. Backup/restore includes pending recruits and associated skill entitlements.

## 4. Barracks capacity

Add 16 barracks berths adds exactly sixteen per click without reducing capacity. Pre-recruit checks include existing members and pending deliveries to prevent repeated clicks from overbooking.

Expand when the launcher reports insufficient space. The receiving client also enforces capacity.

Nation captions use full names and the garage order: China, USSR, USA, Germany, Czechoslovakia, France, UK, Japan, Poland, Sweden, limited to available nations.

## 5. Garage and styles

Garage tools expose available legal vehicles. Coatings can add compatible preset styles, fill missing inventory and edit copies. Hidden styles still require vehicle compatibility.

Rental copies retain original battle counts. Saving/restarting does not refill them indefinitely. After first unlocked-style initialization, use or sale does not repeatedly replenish stock.

## 6. Maintenance modes

| Action | Scope |
| --- | --- |
| Repair mod installation | Reinstall this launcher's bundled payload while keeping usable saves/profiles; no latest-version download |
| Reset all offline client settings | Reset player/worker and legacy offline graphics, sound and input preferences, without clearing saves or retail preferences |
| Clear all offline saves | Remove every offline save, legacy copies and pending grants; recreate unlocked Default; retain tactics, vehicle profiles and client settings |
| Delete all data and restore factory defaults | Remove project-owned saves, profiles, routes, lineups, settings, history, caches, recordings, logs, reports and recovery residue; restore managed overlays, reinstall and recreate defaults |

All four confirm first. Close games, workers, rooms and other launchers; active background writers/report collection may block maintenance. Successful factory reset closes the launcher; reopen for fresh defaults.

Repair installs the package from the launcher you clicked. An older package followed by a newer package changes the installed shared payload accordingly; packages do not each own independent game-mod installations.

Offline data is shared across launcher versions, so clearing it affects other versions. Files manually copied to other locations are not deleted.

## 7. Important distinctions

Initialize affects one selected save. Clear all saves affects all saves. Factory reset additionally clears routes, profiles, settings, recordings and reports.

Read-only tactical Default and the fully unlocked default save are different objects. Switching saves does not switch tactics; restoring routes does not initialize crew/accounts.

Source checks: save_slots.py, save_customizations.py, save_ledger.py, crew_store.py, crew_ui.py, nation_choices.py, core.py and wot_launcher.py maintenance handling.
