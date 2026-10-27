# Vehicle Fittings, Ammunition and Bot Shell-Switching Policy

Version: 1.0.0. Supported client: Chinese HD World of Tanks 0.9.22.0.1 #1513.

## 1. Three independent configuration layers

Development chooses chassis, engine, turret, gun and other modules. Equipment, directives, consumables and crew provide the effects of a legal fitting. Ammunition policy chooses the carried shells and when to switch them. These layers can be configured independently.

The vehicle whitelist in this guide is the preferred-gun table. The gun whitelist is the weapon-specific shell-policy table. Neither is the battle-eligible vehicle list, and “gun” does not mean the SPG vehicle class. See Guide 6 for eligibility.

## 2. Development, equipment, consumables and crew

Development offers Stock, Intermediate and Fully developed. Native module compatibility, turret/gun pairing, load and equipment installation checks remain in force. Special preferred guns used by top-module fitting are listed in Appendix A.

Equipment has four presets: none, one item, three standard items, or three improved items plus the matching directive. The actual items come from the vehicle's legal fitting. Stock development only permits no equipment.

Consumables offer none; small first-aid kit, small repair kit and manual extinguisher once; the same small items with repeat use; or large first-aid kit, large repair kit and automatic extinguisher with repeat use.

Crew presets are 50%, 75%, 100% full Repairs/Camouflage, and 100% all applicable full skills. All-skills eligibility follows each real seat and combined roles; it is not a fixed set of thirteen identical skills for every seat.

These settings apply to Bots. The player's fully unlocked save separately starts with full-skill crew, three legal improved devices, the matching directive and directive resupply. Saved player changes are not repeatedly overwritten on startup.

## 3. Default ammunition allocation

Without a manual ratio, the policy identifies the installed gun's main, backup and HE shells before distributing stock. Appendix B specifies special combinations; other guns use price category, shell kind and original index ordering.

| Situation | Default weights |
| --- | --- |
| Ordinary gun, main/enhanced/HE | 60/30/10 |
| Ordinary gun, two non-HE types | 60/40 |
| Ordinary gun, two types including HE | 80/20 |
| HE-primary gun, main HE and one non-HE backup | 80/20 |
| Single-shot SPG, regular and enhanced HE | 80/20 |
| Magazine SPG, regular and enhanced HE | 75/25 |
| One valid shell type | All ammunition uses that type |

SPGs use HE only by default; AP is not automatically added as their second default shell. A gun with one HE type carries that type. Enhanced HE must really exist on that gun.

Weights are not exact integer percentages on every vehicle. Single-shot guns allocate rounds, magazine guns allocate complete magazines, and an indivisible remainder goes to the main shell without enlarging the magazine. When capacity allows, each valid choice receives at least one allocation unit. A one-round limit remains one round total, not one round of every type.

## 4. Manual ratios and ammunition limits

Open Bot tactics, then Behavior parameters. Ratio entries are integer weights from 0 to 9. Zero excludes that type; all zero carries no ammunition. Their displayed order follows the actual shell ordering, not a universal AP/APCR/HE slot interpretation.

Manual ratios replace default shell filtering and can explicitly select shells supported by the installed gun. They cannot create unsupported shells.

The optional total limit is an integer from 0 to 1800. Actual stock is capped by the gun's native capacity. Zero means empty; one means one round total. This changes neither player stock nor native capacity or magazine size.

An empty magazine, an ongoing reload, or an empty current type with other rounds remaining is not complete ammunition exhaustion. Guide 3 covers the confirmed-empty state.

## 5. Switching conditions

Decisions use terminal results of actual launched shots, not aiming animation or predicted damage. The table describes default shell combinations. A manually replaced combination uses its actual available stages and does not receive newly invented enhanced HE.

| Gun category | Failure counted | Default threshold |
| --- | --- | --- |
| Ordinary main gun | A hit dealing no vehicle HP damage | Two failures select the next available policy stage |
| HE-primary gun | A direct hit that did not penetrate | Two failures try the designated non-HE backup |
| SPG | Neither a hit nor any damage | Two failures try stocked enhanced HE |
| Multiple projectiles per trigger | Aggregate the group actually launched, then apply its category's rule | One failed trigger group |

Positive HP damage clears an ordinary gun's failure count. A pure miss is not a zero-damage hit. HE-primary success requires a direct penetration; splash is not a direct hit. An SPG hit or splash damage clears its failure count.

A target change or horizontal displacement exceeding three metres from the current context anchor resets the count. Rotation and movement within that area do not continually reset it. Magazine failure counts do not carry across magazines. Unknown results clear the streak; late results from an old target or position do not pollute the new context.

A missing or exhausted backup cannot be selected. When enhanced HE is exhausted, an SPG continues with its remaining valid HE.

## 6. Returning to the main shell

- Magazine guns return after actually firing the full backup magazine. A pending further escalation takes precedence.
- Single-shot HE-primary guns return after one actual non-HE probe shot.
- Single-shot SPGs return to a stocked main HE after two actual enhanced-HE shots.
- An ordinary single-shot gun using its HE stage returns after two actual HE shots.
- An ordinary single-shot gun using a non-HE enhanced shell does not return merely because one shot dealt damage; results and stock continue to govern it.

A decision consumes no ammunition and restarts no reload timer. Actual shell changes follow reload/magazine handoff. Shots already in flight keep their frozen shell and normal settlement.

## 7. Appendix A: preferred-gun vehicle whitelist

This table controls preferred module installation, not a rule forcing every stock or intermediate fitting to use the listed gun. Explicit launcher development choices retain their effective semantics. Stable identifiers distinguish similarly named variants.

33 vehicles.

| Nation | Resource name | Full vehicle ID | Preferred gun ID |
| --- | --- | --- | --- |
| China | Ch05 T34 2 | china:Ch05_T34_2 | _100mm_59-100T |
| France | S 35CA | france:F33_S_35CA | Canon_de_105_mle_1930_Schneider_AC |
| Germany | Hetzer | germany:G09_Hetzer | _105mm_StuH42_L28 |
| Germany | Gtraktor Krupp | germany:G100_Gtraktor_Krupp | _75mm_KwK_37_L24A |
| Germany | StuG III | germany:G101_StuG_III | _105mm_StuH42_L28 |
| Germany | Pz IV AusfH | germany:G81_Pz_IV_AusfH | _105mm_StuH42_L28Pz |
| Germany | Pz IV AusfA | germany:G83_Pz_IV_AusfA | _75mm_KwK_37_L24 |
| Germany | Waffentrager IV | germany:G97_Waffentrager_IV | _128mm_K44_2_L61 |
| Germany | RhB Waffentrager | germany:G99_RhB_Waffentrager | _128mm_K44_L55 |
| Japan | Type 2605 | japan:J20_Type_2605 | _150mm_45_41st_Year_Type |
| Japan | Mi To | japan:J23_Mi_To | _120mm_Short_Barrel_Gun |
| Japan | Mi To 130 tons | japan:J24_Mi_To_130_tons | _150mm_Howitzer_Type96 |
| Japan | Type 4 | japan:J25_Type_4 | _150mm_45_41st_Year_Type |
| Japan | O I 120 | japan:J27_O_I_120 | _150mm_Howitzer_Type96 |
| Japan | O I 100 | japan:J28_O_I_100 | _150mm_Howitzer_Type96 |
| Sweden | Sav M43 | sweden:S19_Sav_M43 | _105mm_kan_m_44_sav |
| UK | Centurion Mk3 | uk:GB24_Centurion_Mk3 | _105mm_Gun_L7 |
| UK | FV215b 183 | uk:GB48_FV215b_183 | _183mm_L4 |
| UK | AT15 | uk:GB72_AT15 | _32-pounder_AT_Gun_OQF |
| UK | Charioteer | uk:GB80_Charioteer | _105mm_AT_Gun_L7 |
| UK | FV4004 | uk:GB81_FV4004 | _5_5inch_AT_Gun |
| UK | FV4005 | uk:GB83_FV4005 | _183mm_AT_Gun |
| USA | T49 | usa:A100_T49 | _152mm_Gun_Launcher_M81 |
| USA | XM551 | usa:A116_XM551 | _152mm_Gun_Launcher_M81 |
| USSR | KV85 | ussr:R106_KV85 | _100mm_S34 |
| USSR | ISU130 | ussr:R111_ISU130 | _130mm_S-26A |
| USSR | A-20 | ussr:R12_A-20 | _45mm_VT-42 |
| USSR | SU-152 | ussr:R18_SU-152 | _152mm_ML-20_mod_1937 |
| USSR | T-44 | ussr:R20_T-44 | _100mm_LB-1 |
| USSR | T-46 | ussr:R22_T-46 | _45mm_VT-42 |
| USSR | T80 | ussr:R44_T80 | _45mm_VT-43 |
| USSR | SU100Y | ussr:R49_SU100Y | _130mm_B-13-S2 |
| USSR | KV2 | ussr:R77_KV2 | _152mm_M-10 |

## 8. Appendix B: weapon ammunition-policy whitelist

“Gun” includes ordinary tank guns and SPG weapons. Matching uses nation plus installed weapon ID, independently of the vehicle preferred-gun table. Another vehicle mounting the same gun uses that gun's policy.

The first shell is the main policy stage; subsequent entries are backups. These roles do not guarantee a silver AP first and a premium second: HE-primary exceptions use the explicit order below. Unlisted weapons retain generic allocation. Canonical shell IDs are kept to make the list unambiguous in either language.

43 weapons.

| Nation | Gun ID | Main shell ID | Backup 1 ID | Backup 2 ID |
| --- | --- | --- | --- | --- |
| China | china:_57mm_Gun_Type_97 | _57mm_HE_Type_97 | _57mm_HEAT_Type_97 | — |
| France | france:Canon_de_105_court_mle_1934S_AC | _105mm_OE_mle_1920 | _105mm_OCO_mle._1936 | — |
| France | france:Canon_de_105_court_mle_1934S_T | _105mm_OE_mle_1920 | _105mm_OCO_mle._1936 | — |
| France | france:_105mm_leFH18_L28 | _105mm_Sprg_K | — | — |
| France | france:_47mm_SA34 | _47mm_Oe_type_D | _47mm_Odr_mle_1935_b | — |
| Germany | germany:_105mm_StuH42_L28 | _105mm_Sprg_K | _105mmGr39H1A | — |
| Germany | germany:_105mm_StuH42_L28Pz | _105mm_Sprg_K | _105mmGr39H1A | — |
| Germany | germany:_75mm_KwK_37_L24 | _75mm_Sprg.18 | _Gr_38_HL_A | — |
| Germany | germany:_75mm_KwK_37_L24A | _75mm_Sprg.18 | _Gr_38_HL_A | — |
| Germany | germany:_75mm_StuK_37_L24 | _75mm_Sprg.18 | _Gr_38_HL_A | — |
| Japan | japan:_120mm_Short_Barrel_Gun | _120mm_HE_Commerce_Raid | _120mm_HEAT_Type_88 | — |
| Japan | japan:_150mm_45_41st_Year_Type | _150mm_Common_Type_0_HE_Kai | — | — |
| Japan | japan:_150mm_Howitzer_Type96 | _150mm_HE_Type96 | _150mm_HEAT_Type3 | — |
| Japan | japan:_57mm_Gun_Type90 | _57mm_HE_Type97 | _57mm_HEAT_Type97 | — |
| Japan | japan:_57mm_Gun_Type97 | _57mm_HE_Type97 | _57mm_HEAT_Type97 | — |
| Japan | japan:_70mm_Gun_Type_94 | _70mm_HE_Type92 | _70mm_HEAT_Type3 | — |
| Sweden | sweden:_105mm_kan_m_44_sav | _105mm_lt_sgr_m_34 | _105mm_psgr_m_49 | — |
| UK | uk:_105mm_AT_Gun_L7 | _105mm_HESH_L7 | _105mm_APCR_L7 | — |
| UK | uk:_105mm_Gun_L7 | _105mm_HESH_L7 | _105mm_APCR_L7 | — |
| UK | uk:_105mm_SPH_M4_L23 | _105mm_HE_M1 | _105mm_HEAT_M67 | — |
| UK | uk:_183mm_AT_Gun | _183mm_HESH | _183mm_AP_Mk1 | — |
| UK | uk:_183mm_L4 | _183mm_HESH | _183mm_AP_Mk1 | — |
| UK | uk:_25pdr_Field_Gun | _25pdr_HE_Mk_1D | — | — |
| UK | uk:_3.7inch_AT_Howitzer | _3.7inch_HE_Mk3 | _3.7inch_HEAT_Mk1 | — |
| UK | uk:_3.7inch_Howitzer | _3.7inch_HE_Mk3 | _3.7inch_HEAT_Mk1 | — |
| UK | uk:_5_5inch_AT_Gun | _5_5inch_HESH_Mk_1 | _5_5inch_AP_Mk_1 | — |
| UK | uk:_76mm_Howitzer_MkI | _76mm_HE_MkI | _76mm_HEAT_MkI | — |
| USA | usa:_105mm_AT_Howitzer_M3 | _105mm_HE_M1 | _105mm_HEAT_M67 | — |
| USA | usa:_105mm_AT_SPH_M4_L23 | _105mm_HE_M1 | _105mm_HEAT_M67 | — |
| USA | usa:_105mm_SPH_M4_L23 | _105mm_HE_M1 | _105mm_HEAT_M67 | — |
| USA | usa:_152mm_Gun_Launcher_M81 | _152mm_HE_XM657E3 | _152mm_HEAT_XM409 | — |
| USA | usa:_75mm_AT_Howitzer_M3 | _75mm_M48 | _75mm_HEAT_M66 | — |
| USA | usa:_75mm_Howitzer_M1A1 | _75mm_M48 | _75mm_HEAT_M66 | — |
| USA | usa:_75mm_Howitzer_M3 | _75mm_M48 | _75mm_HEAT_M66 | — |
| USSR | ussr:_122mm_S-41 | _122mm_OF420S | _122mm_BP450S | — |
| USSR | ussr:_122mm_cannon_M-30S | _122mm_OF420S | _122mm_BP450S | — |
| USSR | ussr:_122mm_cannon_U-11 | _122mm_OF420S | _122mm_BP450S | — |
| USSR | ussr:_130mm_B-13-S2 | _130mm_PB-46A | _130mm_PB-46 | _130mm_OF-46 |
| USSR | ussr:_130mm_S-26A | _130mm_2-01743 | _130mm_2-02864A | _130mm_2-02742 |
| USSR | ussr:_152mm_M-10 | _152mm_53-OF-530 | _152mm_MPB_1915 | — |
| USSR | ussr:_152mm_ML-20_mod_1937 | _152mm_53-OF-530 | _152mm_53BP540 | — |
| USSR | ussr:_76mm_KT-28 | _76mm_UOF-354K | _76mm_BP-354 | — |
| USSR | ussr:_76mm_KT-28A | _76mm_UOF-354K | — | — |

Source checks: default_loadouts.py, ammo_policy.py, bot_fittings.py, vehicle_configuration.py and the supported client catalogue.
