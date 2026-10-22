# Bot fitting tiers (#1513)

The resolved Bot skill label selects a discrete native fitting. Continuous
reaction, aim and tactical ratings remain unchanged. An explicit tactics
crew-level override wins over the tier default. Player garage fittings and
ammunition defaults are unchanged.

| Tier | Modules | Crew | Skills | Devices | Directive | Outfit |
| --- | --- | --- | --- | --- | --- | --- |
| rookie | Native stock | 50 | None | None | None | Native appearance |
| regular | Reviewed intermediate | 75 | None | First legal regular device | None | Native appearance |
| veteran | Reviewed fully upgraded | 100 | Repair and camouflage, all seats | Three legal regular devices | None | Native appearance |
| elite | Reviewed fully upgraded | 100 | All role-legal skills from sandbox mask | Three legal purple devices | First installed device's booster | Native nation's rented style, all seasons, no Bot expiry |

Intermediate modules use fully upgraded chassis, the second engine and radio
from the stock end of the native garage order, and the gun immediately below
the reviewed full gun in the descending garage list. At the end of any list,
retain the available endpoint. Select the gun first, then prefer the native
stock turret when compatible. Otherwise use a compatible turret. Premium
vehicles retain their fixed module configuration at all four tiers.

Device family priority is stabilizer, rammer, laying drive, ventilation,
coated optics, toolbox. Skip a family rejected by the native vehicle filters;
use the correct legal regular variant and never repeat a family. Installation
also checks native admission tuples and the resulting serialized descriptor.

## Configuration exceptions (separate from gun ammunition policies)

These are the reviewed 33 intermediate guns. Fully upgraded guns continue to
use `default_loadouts.VEHICLE_GUNS`. Turrets always follow gun compatibility;
intermediate fittings prefer stock turrets. Gun-keyed ammunition policy,
ratios, physical shell identities/prices and shot-result switching are retained.

| Vehicle identity | Regular gun | Fully upgraded gun |
| --- | --- | --- |
| china:Ch05_T34_2 | _100mm_44-100JT | _100mm_59-100T |
| france:F33_S_35CA | _90mm_canon_DCA_30_CA | Canon_de_105_mle_1930_Schneider_AC |
| germany:G09_Hetzer | _75mm_PaK_39_L48 | _105mm_StuH42_L28 |
| germany:G100_Gtraktor_Krupp | _75mm_KwK_37_L24A | _75mm_KwK_37_L24A |
| germany:G101_StuG_III | _75mm_PaK_39_L48 | _105mm_StuH42_L28 |
| germany:G81_Pz_IV_AusfH | _75mm_KwK_40_L48 | _105mm_StuH42_L28Pz |
| germany:G83_Pz_IV_AusfA | _50mm_KwK_38_L42 | _75mm_KwK_37_L24 |
| germany:G97_Waffentrager_IV | _150mm_Rohr_L38 | _128mm_K44_2_L61 |
| germany:G99_RhB_Waffentrager | _150mm_Rohr_L29_5 | _128mm_K44_L55 |
| japan:J20_Type_2605 | _140mm_50_3rd_Year_Type | _150mm_45_41st_Year_Type |
| japan:J23_Mi_To | _75mm_Gun_Type5 | _120mm_Short_Barrel_Gun |
| japan:J24_Mi_To_130_tons | _105mm_Cannon_Type92 | _150mm_Howitzer_Type96 |
| japan:J25_Type_4 | _140mm_50_3rd_Year_Type | _150mm_45_41st_Year_Type |
| japan:J27_O_I_120 | _105mm_Experimental_Tank_Gun_Kai | _150mm_Howitzer_Type96 |
| japan:J28_O_I_100 | _105mm_Experimental_Tank_Gun | _150mm_Howitzer_Type96 |
| sweden:S19_Sav_M43 | _75mm_kan_m_41_ikv_L_50_neglkrut | _105mm_kan_m_44_sav |
| uk:GB24_Centurion_Mk3 | _20pdr_Gun_Type_B | _105mm_Gun_L7 |
| uk:GB48_FV215b_183 | _183mm_L4 | _183mm_L4 |
| uk:GB72_AT15 | _20pdr_AT_Gun_Type_B | _32-pounder_AT_Gun_OQF |
| uk:GB80_Charioteer | _20pdr_AT_Gun_Type_B | _105mm_AT_Gun_L7 |
| uk:GB81_FV4004 | _120mm_AT_Gun_L1A1 | _5_5inch_AT_Gun |
| uk:GB83_FV4005 | _183mm_AT_Gun | _183mm_AT_Gun |
| usa:A100_T49 | _90mm_Gun_T132E3 | _152mm_Gun_Launcher_M81 |
| usa:A116_XM551 | _105mm_Lightweight_Gun | _152mm_Gun_Launcher_M81 |
| ussr:R106_KV85 | _122-mm_D-25T_with_a_piston_shutter | _100mm_S34 |
| ussr:R111_ISU130 | _130mm_S-26A | _130mm_S-26A |
| ussr:R12_A-20 | _76mm_L-11 | _45mm_VT-42 |
| ussr:R18_SU-152 | _122mm_D-25C_mod1944 | _152mm_ML-20_mod_1937 |
| ussr:R20_T-44 | _100mm_D10T | _100mm_LB-1 |
| ussr:R22_T-46 | _76mm_L-10 | _45mm_VT-42 |
| ussr:R44_T80 | _45mm_VT-42 | _45mm_VT-43 |
| ussr:R49_SU100Y | _130mm_B-13-S2 | _130mm_B-13-S2 |
| ussr:R77_KV2 | _107mm_ZiS-6 | _152mm_M-10 |

## Native outfit exceptions

These 22 identities retain native appearance and inherent concealment. They
receive no added rented-style camouflage bonus. Both native `lockOutfit` tags
and rented-style exclusions are accounted for, including AMX 13 57 GF and
WZ-111 Alpine Tiger.

- `china:Ch01_Type59_Gold`
- `china:Ch03_WZ_111_A`
- `china:Ch22_113_Beijing_Opera`
- `france:F69_AMX13_57_100_GrandFinal`
- `france:F74_AMX_M4_1949_Liberte`
- `germany:G04_PzVI_Tiger_IA`
- `germany:G114_Rheinmetall_Skorpian`
- `germany:G119_Panzer58_BF`
- `germany:G119_Pz58_Mutz`
- `germany:G120_M41_90_GrandFinal`
- `germany:G136_Tiger_131`
- `japan:J29_Nameless`
- `japan:J30_Edelweiss`
- `poland:Pl03_PzV_Poland`
- `sweden:S23_Strv_81_sabaton`
- `usa:A115_Chrysler_K`
- `usa:A117_T26E5_Patriot`
- `usa:A13_T34_hvy_BF`
- `usa:A63_M46_Patton_KR`
- `ussr:R134_Object_252K`
- `ussr:R146_STG_Tday`
- `ussr:R61_Object252_BF`

## Shared identity and mutable state

A fitting envelope includes vehicle, resolved tier, trained crew level,
serialized native vehicle descriptor, devices, directive and style. Worker,
server, visible replicas and authority restoration retain this exact envelope.
Caches distinguish same-vehicle tiers and explicit crew overrides. The native
travel/Siege descriptor pair shares one crew/directive context. Weapon,
ammunition, consumable and critical state remain per Bot.

Native crew generation filters skills by each seat's combined roles. Native
attribute-factor processors apply crew, mounted devices and the directive;
there are no invented purple multipliers. Seasonal hull camouflage is passed
to the native base-invisibility calculation once. Native item/crew rejection
is logged and surfaced, rather than silently becoming a 100% default crew.
Round teardown clears descriptor contexts after native presentation cleanup.
Native rented styles contain empty EVENT outfits. Preserve their serialized
empty appearance and use no hull camouflage ID/bonus; an absent camouflage
is not an ambiguous fitting. All nine national styles / 36 seasonal outfits
are included in the exact-client resource audit.

## Validation

- `python tools/run_test_suite.py --pattern test_bot_fittings.py`
- Existing Bot gunnery, runtime, presentation, server manifest/takeover and
  tier-consumable suites remain enabled; crew expectations now use 50/75/100/100.
- `python tools/verify_bot_fittings.py CLIENT --output AUDIT.json` checks all
  576 vehicles / 2304 plans against exact packed resources: modules, compatible
  turrets, stock-turret preference, intermediate engines/radios, premium fixed
  modules, device filters/load, native health/reload, full ammunition and whole
  magazines. It preserves repeated native filter clauses.
- Compile client source with CPython 2.7; verify the final packed bytecode and
  frozen server against source, plus matching x86 native payload and launcher
  launch entries.

Static resource and adapter checks do not establish BigWorld rendering,
installation lifetime, performance or gameplay acceptance on the real client.
The test package records one `BOT FITTING` line per unique configuration to
make any native admission or fitted-model discrepancy identifiable.
