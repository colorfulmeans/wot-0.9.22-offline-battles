# Bot Difficulty and Launcher Parameter Configuration

Version: 1.0.0. Supported client: Chinese HD World of Tanks 0.9.22.0.1 #1513.

## 1. Room difficulty and per-Bot skill

The room offers Mixed, Rookie, Regular, Veteran and Elite. It selects the team's rating distribution. Pinning Rookie/Regular/Veteran/Elite for an individual launcher slot instead selects that skill's fixed anchor. These are separate controls.

Ratings range from zero to one. They govern reaction, aiming tolerance/bias, moving-target lead and probabilities of some tactics. They do not directly rewrite penetration, damage or armour.

| Room setting | Internal value | Rating range | Distribution mean |
| --- | --- | --- | --- |
| Rookie | easy | 0–0.30 | 0.10 |
| Regular | relaxed | 0.05–0.67 | 0.30 |
| Mixed | mixed | 0.12–1.00 | 0.60 |
| Veteran | hard | 0.52–1.00 | 0.80 |
| Elite | brutal | Exactly 1.00 | 1.00 |

A mean is an expectation, not the exact average of every match. Except for Elite, slots draw within the distribution. A round/team/slot combination retains the same result rather than rerolling every update.

## 2. Four individual skill anchors

| Parameter | Rookie | Regular | Veteran | Elite |
| --- | --- | --- | --- | --- |
| Rating | 0 | 0.34 | 0.67 | 1.00 |
| Default main crew training | 50% | 75% | 100% | 100% |
| Reaction delay | 1.20 s | 0.75 s | 0.45 s | 0.25 s |
| Opening aim patience | 0.60 s | 1.10 s | 1.70 s | 2.40 s |
| Accepted dispersion factor | 2.60 | 1.80 | 1.35 | 1.12 |
| Aim-point bias factor | 1.80 | 0.85 | 0.35 | 0.10 |
| Lead error | 45% | 22% | 9% | 2% |

Reaction and aiming parameters interpolate between anchors; crew and fittings use discrete tiers. A larger accepted dispersion factor permits a larger aiming circle. Longer patience means waiting longer for aim, not a slower reaction.

Bias uses the real gun's accuracy. Rating is neither hit probability nor a guarantee of penetration. Better tactics still require real visibility, gun limits, ballistics and obstacle checks.

## 3. Default fitting tiers

| Tier | Development | Equipment/directive | Crew |
| --- | --- | --- | --- |
| Rookie | Stock | None | 50%, no additional ordinary skills |
| Regular | Intermediate | One legal device | 75%, no additional ordinary skills |
| Veteran | Fully developed | Three legal standard devices | 100%, full Repairs/Camouflage |
| Elite | Fully developed | Three legal improved devices and matching directive | 100%, all applicable full skills |

Per-vehicle generated plans choose actual legal items. Three devices does not mean the same three on every tank. Special vehicles, locked outfits and gun exceptions retain their own data. Consumables can be configured separately.

## 4. Launcher workflow

1. Open Bot tactics and Behavior parameters.
2. Default is read-only. Create or select an editable independent profile.
3. Choose team, vehicle class and slot scope. Set only the fields to override; blanks inherit.
4. Use Add/update rule to write the form into the rule list.
5. Inspect effective parameters for the selected scope.
6. Save a draft or Save and apply (next battle). An existing battle does not reload an edited draft.

Changing a dropdown is not the same as updating its rule. Saving a draft is not the same as applying it. Undo/redo belongs to the current editor draft.

## 5. Inheritance and precedence

Rules generally progress from global to team, class and specific slot. Each field inherits independently. A slot overriding reaction can still inherit development and equipment.

A specific slot requires a team. Duplicate team/class/slot selectors are refused. Canonical ordering and the effective preview determine intersecting scopes; do not infer precedence solely from visual list position.

Fixed launcher vehicles are retained instead of being replaced by random room selection. Explicit skill and parameter settings apply in their scopes; unoverridden values follow room and parent settings.

## 6. Editable numeric limits

| Parameter | Range | Meaning |
| --- | --- | --- |
| Reaction delay | 0–5 s | Delay after acquiring a firing solution |
| Opening aim patience | 0–10 s | Initial willingness to wait for convergence |
| Accepted dispersion factor | 1–5 | Relative to the fully aimed circle |
| Aim-point bias | 0–4 | Error relative to gun accuracy |
| Lead error | 0–100% | Fractional moving-target lead error |
| Ammunition limit | Integer 0–1800 | Total Bot stock, capped by native capacity |
| Ammunition ratio | Each entry integer 0–9 | Shell allocation weights |

Zero is a real valid value for several parameters, not inheritance. Use blank/Inherit for inheritance. Stock development only permits no equipment; invalid combinations are checked in the editor and on save.

See Guide 1 for independent presets. Legacy crew-level fields retain 75/90/100 compatibility values; they differ from the new 50/75/full-skill crew presets.

## 7. Profile management

Profiles support create, rename, delete, import, export, draft saving and next-battle application. Conflicting imported names receive independent names. Restoring the default draft changes the custom draft, not a running match.

Language switching preserves selections and unsaved input. Limits, validation text and previews follow the current language.

Source checks: bot_gunnery.py, bot_fittings.py, bot_tactics.py, bot_tactics_labels.py, bot_tactics_ui.py and bot_lineup_profiles.py.
