# Known Internal Vehicle Module Issues

Version: 1.0.0. Supported client: Chinese HD World of Tanks 0.9.22.0.1 #1513.

Checked: 27 October 2026.

## 1. Scope

This list scans all 680 supported-client vehicle definitions against current internal module/crew layouts. It records location-geometry coverage, not a claim that every gap is a reproduced gameplay defect or the sole test of battle eligibility.

Internal targets include engine, fuel, ammo rack, radio, vision device and turret rotator. Gun and left/right tracks also have native exterior hit paths. Missing interior geometry does not mean every exterior module fails, module HP is absent or repair is impossible.

## 2. Coverage summary

| Category | Count | Meaning |
| --- | --- | --- |
| Decoded interior layout | 650 | Decoded source exists, possibly with partial omissions |
| No usable interior layout | 22 | No current usable layout source |
| Reconstructed layout | 8 | Retained reconstruction, not an exact decoded layout of that vehicle |
| Partial omissions among decoded layouts | 176 | Subset of the 650, not additional entries |

650+22+8=680. Of the decoded layouts, 474 have no module/crew omission recorded by this source inventory. That is not native acceptance of every turret/model variant.

Partial omissions concern vision devices, turret rotators and some crew slots in two definitions. A missing turret-rotator geometry on a casemate without that device is not automatically an error; actual hardware must be considered.

All 658 compiled profiles have crew roles matching the client definitions. This is a source/compiled-record inventory, not a newly discovered or repaired model-collision defect.

## 3. Effects and current handling

- No layout: do not invent random engine, rack or crew contacts from vehicle class. Geometry-dependent interior hits have a coverage gap.
- Reconstruction: a layout exists, but its origin differs from exact decoded geometry.
- Partial omission: only the listed targets are missing; other covered targets are not declared absent.
- Unusable resources: listed independently and normally already excluded from vehicle choices.
- Nonstandard or Bot-only exclusions: follow Guide 6; appearing here does not re-admit an entry to the random pool.

Manual-only retired means a loadable retired player vehicle explicitly excluded from Bots. Nonstandard means filtered event/tutorial/placeholder content. Names below are readable resource names; full IDs are authoritative across languages.

## 4. Vehicles without a usable interior layout

22 entries. This refers to internal module/crew sources, not native gun/track hit geometry.


| Nation | Resource name | Full vehicle ID | Eligibility |
| --- | --- | --- | --- |
| China | Ch40 WZ120G FT | china:Ch40_WZ120G_FT | Retained by standard eligibility checks |
| China | Ch25 121 mod 1971B | china:Ch25_121_mod_1971B | Retained by standard eligibility checks |
| Germany | Tiger 131 | germany:G136_Tiger_131 | Retained by standard eligibility checks |
| Germany | PzIII AusfJ training | germany:G10_PzIII_AusfJ_training | Nonstandard battle entry |
| Germany | PzVIB Tiger II training | germany:G16_PzVIB_Tiger_II_training | Nonstandard battle entry |
| Germany | PzV Panther training | germany:G03_PzV_Panther_training | Nonstandard battle entry |
| Germany | T-55 NVA DDR | germany:G105_T-55_NVA_DDR | Retained by standard eligibility checks |
| Japan | Nameless | japan:J29_Nameless | Retained by standard eligibility checks |
| Japan | Edelweiss | japan:J30_Edelweiss | Retained by standard eligibility checks |
| UK | T95 Chieftain turret | uk:GB88_T95_Chieftain_turret | Retained by standard eligibility checks |
| USA | T23 | usa:A08_T23 | Unusable resources; excluded |
| USA | T23E3 | usa:A86_T23E3 | Retained by standard eligibility checks |
| USA | M4A3E8A | usa:A104_M4A3E8A | Retained by standard eligibility checks |
| USA | M48A2 120 | usa:A106_M48A2_120 | Retained by standard eligibility checks |
| USSR | Observer | ussr:Observer | Nonstandard battle entry |
| USSR | T44 85 | ussr:R98_T44_85 | Retained by standard eligibility checks |
| USSR | T44 85M | ussr:R98_T44_85M | Retained by standard eligibility checks |
| USSR | Object 777 | ussr:R119_Object_777 | Retained by standard eligibility checks |
| USSR | T22SR A22 | ussr:R120_T22SR_A22 | Retained by standard eligibility checks |
| USSR | KV4 KTT | ussr:R121_KV4_KTT | Retained by standard eligibility checks |
| USSR | Object 730 5 | ussr:R126_Object_730_5 | Retained by standard eligibility checks |
| USSR | Object 257 | ussr:R129_Object_257 | Retained by standard eligibility checks |

## 5. Vehicles using reconstructed layouts

Eight entries. Reconstruction is retained and is not labelled exact interior-model completion.

| Nation | Resource name | Full vehicle ID | Eligibility |
| --- | --- | --- | --- |
| France | AMX 13F3AM | france:F23_AMX_13F3AM | Retained by standard eligibility checks |
| Germany | Pz IV AusfGH | germany:G79_Pz_IV_AusfGH | Unusable resources; excluded |
| UK | FV4202 105 | uk:GB70_FV4202_105 | Unusable resources; excluded |
| USA | T57 | usa:A15_T57 | Unusable resources; excluded |
| USA | T18 | usa:A26_T18 | Unusable resources; excluded |
| USA | T28 | usa:A39_T28 | Retained by standard eligibility checks |
| USSR | KV | ussr:R05_KV | Unusable resources; excluded |
| USSR | T 50 2 | ussr:R70_T_50_2 | Unusable resources; excluded |

## 6. Partial omissions in decoded layouts

176 entries. Crew seats below are one-based and include duties; they are not zero-based code indices. Missing means current interior location geometry.

| Nation | Resource name | Full vehicle ID | Missing targets | Eligibility |
| --- | --- | --- | --- | --- |
| China | Ch30 T-26G FT | china:Ch30_T-26G_FT | Turret rotator | Retained by standard eligibility checks |
| China | Ch31 M3G FT | china:Ch31_M3G_FT | Vision device; Turret rotator | Retained by standard eligibility checks |
| China | Ch32 SU-76G FT | china:Ch32_SU-76G_FT | Turret rotator | Retained by standard eligibility checks |
| China | Ch33 60G FT | china:Ch33_60G_FT | Turret rotator | Retained by standard eligibility checks |
| China | Ch34 WZ131G FT | china:Ch34_WZ131G_FT | Turret rotator | Retained by standard eligibility checks |
| China | Ch35 T-34-2G FT | china:Ch35_T-34-2G_FT | Turret rotator | Retained by standard eligibility checks |
| China | Ch36 WZ111 1G FT | china:Ch36_WZ111_1G_FT | Turret rotator | Retained by standard eligibility checks |
| China | Ch37 WZ111G FT | china:Ch37_WZ111G_FT | Turret rotator | Retained by standard eligibility checks |
| China | Ch38 WZ113G FT | china:Ch38_WZ113G_FT | Turret rotator | Retained by standard eligibility checks |
| China | Ch39 WZ120 1G FT | china:Ch39_WZ120_1G_FT | Turret rotator | Retained by standard eligibility checks |
| China | Ch24 Type64 | china:Ch24_Type64 | Vision device | Retained by standard eligibility checks |
| France | RenaultBS | france:F20_RenaultBS | Turret rotator | Retained by standard eligibility checks |
| France | 105 leFH18B2 | france:F28_105_leFH18B2 | Vision device; Turret rotator | Retained by standard eligibility checks |
| France | FCM 36Pak40 | france:F27_FCM_36Pak40 | Turret rotator | Retained by standard eligibility checks |
| France | Lorraine39 L AM | france:F21_Lorraine39_L_AM | Vision device; Turret rotator | Retained by standard eligibility checks |
| France | AMX 105AM | france:F22_AMX_105AM | Turret rotator | Retained by standard eligibility checks |
| France | Lorraine155 50 | france:F24_Lorraine155_50 | Vision device; Turret rotator | Retained by standard eligibility checks |
| France | Lorraine155 51 | france:F25_Lorraine155_51 | Vision device; Turret rotator | Retained by standard eligibility checks |
| France | RenaultFT AC | france:F30_RenaultFT_AC | Vision device; Turret rotator | Retained by standard eligibility checks |
| France | RenaultUE57 | france:F52_RenaultUE57 | Turret rotator | Retained by standard eligibility checks |
| France | Somua Sau 40 | france:F32_Somua_Sau_40 | Turret rotator | Retained by standard eligibility checks |
| France | S 35CA | france:F33_S_35CA | Vision device; Turret rotator | Retained by standard eligibility checks |
| France | AMX AC Mle1946 | france:F35_AMX_AC_Mle1946 | Turret rotator | Retained by standard eligibility checks |
| France | AMX50 Foch | france:F37_AMX50_Foch | Turret rotator | Retained by standard eligibility checks |
| France | ARL V39 | france:F34_ARL_V39 | Turret rotator | Retained by standard eligibility checks |
| France | AMX AC Mle1948 | france:F36_AMX_AC_Mle1948 | Turret rotator | Retained by standard eligibility checks |
| France | AMX 50Fosh 155 | france:F64_AMX_50Fosh_155 | Turret rotator | Retained by standard eligibility checks |
| France | Bat Chatillon155 55 | france:F67_Bat_Chatillon155_55 | Vision device | Retained by standard eligibility checks |
| France | AMX Ob Am105 | france:F66_AMX_Ob_Am105 | Vision device; Turret rotator | Retained by standard eligibility checks |
| France | AMX 50Fosh B | france:F64_AMX_50Fosh_B | Turret rotator | Retained by standard eligibility checks |
| France | Canon dassaut de 105 | france:F89_Canon_dassaut_de_105 | Turret rotator | Retained by standard eligibility checks |
| France | AMX AC Mle1948 IGR | france:F36_AMX_AC_Mle1948_IGR | Turret rotator | Nonstandard battle entry |
| France | 105 leFH18B2 IGR | france:F28_105_leFH18B2_IGR | Vision device; Turret rotator | Nonstandard battle entry |
| France | S 35CA IGR | france:F33_S_35CA_IGR | Vision device; Turret rotator | Nonstandard battle entry |
| Germany | Hummel | germany:G02_Hummel | Vision device; Turret rotator | Retained by standard eligibility checks |
| Germany | StuG 40 AusfG | germany:G05_StuG_40_AusfG | Turret rotator | Retained by standard eligibility checks |
| Germany | JagdPzIV | germany:G17_JagdPzIV | Turret rotator | Retained by standard eligibility checks |
| Germany | Hetzer | germany:G09_Hetzer | Turret rotator | Retained by standard eligibility checks |
| Germany | Bison I | germany:G11_Bison_I | Vision device; Turret rotator | Retained by standard eligibility checks |
| Germany | PanzerJager I | germany:G21_PanzerJager_I | Vision device; Turret rotator | Retained by standard eligibility checks |
| Germany | JagdPanther | germany:G18_JagdPanther | Turret rotator | Retained by standard eligibility checks |
| Germany | Sturmpanzer II | germany:G22_Sturmpanzer_II | Vision device; Turret rotator | Retained by standard eligibility checks |
| Germany | Grille | germany:G23_Grille | Vision device; Turret rotator | Retained by standard eligibility checks |
| Germany | Wespe | germany:G19_Wespe | Vision device; Turret rotator | Retained by standard eligibility checks |
| Germany | Marder II | germany:G20_Marder_II | Vision device; Turret rotator | Retained by standard eligibility checks |
| Germany | Ferdinand | germany:G37_Ferdinand | Turret rotator | Retained by standard eligibility checks |
| Germany | JagdTiger | germany:G44_JagdTiger | Turret rotator | Retained by standard eligibility checks |
| Germany | G Tiger | germany:G45_G_Tiger | Vision device; Turret rotator | Retained by standard eligibility checks |
| Germany | G Panther | germany:G49_G_Panther | Vision device | Retained by standard eligibility checks |
| Germany | G E | germany:G61_G_E | Vision device; Turret rotator | Retained by standard eligibility checks |
| Germany | Sturer Emil | germany:G43_Sturer_Emil | Vision device; Turret rotator | Retained by standard eligibility checks |
| Germany | Marder III | germany:G39_Marder_III | Vision device; Turret rotator | Retained by standard eligibility checks |
| Germany | JagdPantherII | germany:G71_JagdPantherII | Turret rotator | Retained by standard eligibility checks |
| Germany | Nashorn | germany:G40_Nashorn | Vision device; Turret rotator | Retained by standard eligibility checks |
| Germany | JagdPz E100 | germany:G72_JagdPz_E100 | Turret rotator | Retained by standard eligibility checks |
| Germany | Auf Panther | germany:G85_Auf_Panther | Vision device; Turret rotator; Seat 1 (commander); Seat 2 (gunner); Seat 5 (loader) | Manual player use; Bot-excluded |
| Germany | GW Mk VIe | germany:G93_GW_Mk_VIe | Vision device; Turret rotator | Retained by standard eligibility checks |
| Germany | GW Tiger P | germany:G94_GW_Tiger_P | Vision device; Turret rotator | Retained by standard eligibility checks |
| Germany | Pz Sfl IVb | germany:G95_Pz_Sfl_IVb | Vision device | Retained by standard eligibility checks |
| Germany | Pz Sfl IVc | germany:G76_Pz_Sfl_IVc | Vision device; Turret rotator | Retained by standard eligibility checks |
| Germany | Waffentrager IV | germany:G97_Waffentrager_IV | Vision device | Retained by standard eligibility checks |
| Germany | RhB Waffentrager | germany:G99_RhB_Waffentrager | Vision device | Retained by standard eligibility checks |
| Germany | Waffentrager E100 | germany:G98_Waffentrager_E100 | Vision device | Manual player use; Bot-excluded |
| Germany | StuG III | germany:G101_StuG_III | Turret rotator | Retained by standard eligibility checks |
| Germany | Grille 15 L63 | germany:G121_Grille_15_L63 | Vision device | Retained by standard eligibility checks |
| Germany | Aufklarungspanzer V | germany:G85_Aufklarungspanzer_V | Vision device; Turret rotator; Seat 1 (commander); Seat 2 (gunner); Seat 5 (loader) | Retained by standard eligibility checks |
| Germany | KanonenJagdPanzer 105 | germany:G112_KanonenJagdPanzer_105 | Turret rotator | Retained by standard eligibility checks |
| Germany | Waffentrager E100 P | germany:G98_Waffentrager_E100_P | Vision device | Retained by standard eligibility checks |
| Germany | JagdTigerH | germany:G44_JagdTigerH | Turret rotator | Retained by standard eligibility checks |
| Germany | Rheinmetall Skorpian | germany:G114_Rheinmetall_Skorpian | Vision device | Retained by standard eligibility checks |
| Germany | JagdTiger SdKfz 185 | germany:G65_JagdTiger_SdKfz_185 | Turret rotator | Retained by standard eligibility checks |
| Germany | E-25 | germany:G48_E-25 | Turret rotator | Retained by standard eligibility checks |
| Germany | DickerMax | germany:G41_DickerMax | Turret rotator | Retained by standard eligibility checks |
| Germany | Stug IV | germany:G104_Stug_IV | Turret rotator | Retained by standard eligibility checks |
| Germany | Steyr WT | germany:G109_Steyr_WT | Vision device | Retained by standard eligibility checks |
| Germany | KanonenJagdPanzer | germany:G112_KanonenJagdPanzer | Turret rotator | Retained by standard eligibility checks |
| Germany | Skorpian | germany:G114_Skorpian | Vision device | Retained by standard eligibility checks |
| Germany | Env Artillery | germany:Env_Artillery | Vision device; Turret rotator | Nonstandard battle entry |
| Germany | JagdTiger SdKfz 185 IGR | germany:G65_JagdTiger_SdKfz_185_IGR | Turret rotator | Nonstandard battle entry |
| Germany | StuG 40 AusfG IGR | germany:G05_StuG_40_AusfG_IGR | Turret rotator | Nonstandard battle entry |
| Germany | E-25 IGR | germany:G48_E-25_IGR | Turret rotator | Nonstandard battle entry |
| Germany | Ferdinand IGR | germany:G37_Ferdinand_IGR | Turret rotator | Nonstandard battle entry |
| Germany | PanzerJager I bootcamp | germany:G21_PanzerJager_I_bootcamp | Vision device; Turret rotator | Nonstandard battle entry |
| Sweden | EMIL 1951 E1 | sweden:S18_EMIL_1951_E1 | Turret rotator | Retained by standard eligibility checks |
| Sweden | L 120 TD | sweden:S09_L_120_TD | Vision device | Retained by standard eligibility checks |
| Sweden | Ikv 72 | sweden:S20_Ikv_72 | Vision device; Turret rotator | Retained by standard eligibility checks |
| Sweden | Sav M43 | sweden:S19_Sav_M43 | Turret rotator | Retained by standard eligibility checks |
| Sweden | Ikv 103 | sweden:S14_Ikv_103 | Turret rotator | Retained by standard eligibility checks |
| Sweden | Ikv 65 Alt 2 | sweden:S08_Ikv_65_Alt_2 | Turret rotator | Retained by standard eligibility checks |
| Sweden | Ikv 90 Typ B Bofors | sweden:S06_Ikv_90_Typ_B_Bofors | Turret rotator | Retained by standard eligibility checks |
| Sweden | UDES 03 | sweden:S21_UDES_03 | Turret rotator | Retained by standard eligibility checks |
| Sweden | Strv 103 0 Series | sweden:S10_Strv_103_0_Series | Turret rotator | Retained by standard eligibility checks |
| Sweden | Strv 103B | sweden:S11_Strv_103B | Turret rotator | Retained by standard eligibility checks |
| Sweden | Strv S1 | sweden:S22_Strv_S1 | Turret rotator | Retained by standard eligibility checks |
| UK | Grant I | uk:GB17_Grant_I | Turret rotator | Retained by standard eligibility checks |
| UK | Sexton | uk:GB27_Sexton | Vision device; Turret rotator | Retained by standard eligibility checks |
| UK | Valentine AT | uk:GB42_Valentine_AT | Vision device; Turret rotator | Retained by standard eligibility checks |
| UK | Universal CarrierQF2 | uk:GB39_Universal_CarrierQF2 | Vision device; Turret rotator | Retained by standard eligibility checks |
| UK | AT15 | uk:GB72_AT15 | Turret rotator | Retained by standard eligibility checks |
| UK | AT2 | uk:GB73_AT2 | Turret rotator | Retained by standard eligibility checks |
| UK | Alecto | uk:GB57_Alecto | Vision device; Turret rotator | Retained by standard eligibility checks |
| UK | AT8 | uk:GB74_AT8 | Turret rotator | Retained by standard eligibility checks |
| UK | Gun Carrier Churchill | uk:GB40_Gun_Carrier_Churchill | Turret rotator | Retained by standard eligibility checks |
| UK | AT7 | uk:GB75_AT7 | Turret rotator | Retained by standard eligibility checks |
| UK | Loyd Gun Carriage | uk:GB25_Loyd_Gun_Carriage | Vision device; Turret rotator | Retained by standard eligibility checks |
| UK | Birch Gun | uk:GB26_Birch_Gun | Vision device; Turret rotator | Retained by standard eligibility checks |
| UK | Bishop | uk:GB28_Bishop | Turret rotator | Retained by standard eligibility checks |
| UK | Crusader 5inch | uk:GB29_Crusader_5inch | Vision device; Turret rotator | Retained by standard eligibility checks |
| UK | FV3805 | uk:GB30_FV3805 | Turret rotator | Retained by standard eligibility checks |
| UK | FV304 | uk:GB77_FV304 | Turret rotator | Retained by standard eligibility checks |
| UK | FV206 | uk:GB79_FV206 | Turret rotator | Retained by standard eligibility checks |
| UK | Conqueror Gun | uk:GB31_Conqueror_Gun | Turret rotator | Retained by standard eligibility checks |
| UK | Archer | uk:GB44_Archer | Vision device; Turret rotator | Retained by standard eligibility checks |
| UK | Achilles IIC | uk:GB45_Achilles_IIC | Vision device | Retained by standard eligibility checks |
| UK | Tortoise | uk:GB32_Tortoise | Turret rotator | Retained by standard eligibility checks |
| UK | FV217 | uk:GB92_FV217 | Turret rotator | Retained by standard eligibility checks |
| UK | AT 15A | uk:GB71_AT_15A | Turret rotator | Retained by standard eligibility checks |
| UK | Sexton I | uk:GB78_Sexton_I | Vision device; Turret rotator | Retained by standard eligibility checks |
| UK | FV304 IGR | uk:GB77_FV304_IGR | Turret rotator | Nonstandard battle entry |
| UK | AT15 IGR | uk:GB72_AT15_IGR | Turret rotator | Nonstandard battle entry |
| USA | M3 Grant | usa:A04_M3_Grant | Turret rotator | Retained by standard eligibility checks |
| USA | M7 Priest | usa:A16_M7_Priest | Vision device; Turret rotator | Retained by standard eligibility checks |
| USA | M41 | usa:A18_M41 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USA | M37 | usa:A17_M37 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USA | M10 Wolverine | usa:A30_M10_Wolverine | Vision device | Retained by standard eligibility checks |
| USA | M40M43 | usa:A37_M40M43 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USA | T40 | usa:A29_T40 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USA | M12 | usa:A32_M12 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USA | T92 | usa:A38_T92 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USA | T95 | usa:A40_T95 | Turret rotator | Retained by standard eligibility checks |
| USA | T25 AT | usa:A64_T25_AT | Turret rotator | Retained by standard eligibility checks |
| USA | T25 2 | usa:A72_T25_2 | Vision device | Retained by standard eligibility checks |
| USA | M18 Hellcat | usa:A41_M18_Hellcat | Vision device | Retained by standard eligibility checks |
| USA | T110E3 | usa:A85_T110E3 | Turret rotator | Retained by standard eligibility checks |
| USA | M44 | usa:A87_M44 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USA | T18 HMC | usa:A108_T18_HMC | Turret rotator | Retained by standard eligibility checks |
| USA | T56 GMC | usa:A109_T56_GMC | Vision device; Turret rotator | Retained by standard eligibility checks |
| USA | T3 | usa:A46_T3 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USA | T82 | usa:A27_T82 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USA | T1 HMC | usa:A107_T1_HMC | Vision device; Turret rotator | Retained by standard eligibility checks |
| USA | M56 | usa:A101_M56 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USSR | SU-85 | ussr:R02_SU-85 | Turret rotator | Retained by standard eligibility checks |
| USSR | S-51 | ussr:R15_S-51 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USSR | SU-152 | ussr:R18_SU-152 | Turret rotator | Retained by standard eligibility checks |
| USSR | SU-100 | ussr:R17_SU-100 | Turret rotator | Retained by standard eligibility checks |
| USSR | SU-18 | ussr:R16_SU-18 | Turret rotator | Retained by standard eligibility checks |
| USSR | SU-14 | ussr:R27_SU-14 | Turret rotator | Retained by standard eligibility checks |
| USSR | SU-5 | ussr:R14_SU-5 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USSR | AT-1 | ussr:R10_AT-1 | Turret rotator | Retained by standard eligibility checks |
| USSR | SU-8 | ussr:R26_SU-8 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USSR | SU-76 | ussr:R24_SU-76 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USSR | GAZ-74b | ussr:R25_GAZ-74b | Vision device; Turret rotator | Retained by standard eligibility checks |
| USSR | ISU-152 | ussr:R47_ISU-152 | Turret rotator | Retained by standard eligibility checks |
| USSR | SU-26 | ussr:R66_SU-26 | Vision device | Retained by standard eligibility checks |
| USSR | Object 704 | ussr:R53_Object_704 | Turret rotator | Retained by standard eligibility checks |
| USSR | Object 212 | ussr:R51_Object_212 | Turret rotator | Retained by standard eligibility checks |
| USSR | Object 261 | ussr:R52_Object_261 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USSR | SU-101 | ussr:R58_SU-101 | Turret rotator | Retained by standard eligibility checks |
| USSR | SU100M1 | ussr:R74_SU100M1 | Turret rotator | Retained by standard eligibility checks |
| USSR | SU122 54 | ussr:R75_SU122_54 | Turret rotator | Manual player use; Bot-excluded |
| USSR | Object268 | ussr:R88_Object268 | Turret rotator | Retained by standard eligibility checks |
| USSR | Object263B | ussr:R93_Object263B | Vision device; Turret rotator | Manual player use; Bot-excluded |
| USSR | SU14 1 | ussr:R91_SU14_1 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USSR | SU122A | ussr:R100_SU122A | Vision device; Turret rotator | Retained by standard eligibility checks |
| USSR | Object 268 4 | ussr:R149_Object_268_4 | Turret rotator | Retained by standard eligibility checks |
| USSR | Object263 | ussr:R93_Object263 | Vision device; Turret rotator | Retained by standard eligibility checks |
| USSR | SU 85I | ussr:R78_SU_85I | Turret rotator | Retained by standard eligibility checks |
| USSR | SU76I | ussr:R50_SU76I | Turret rotator | Retained by standard eligibility checks |
| USSR | SU100Y | ussr:R49_SU100Y | Turret rotator | Retained by standard eligibility checks |
| USSR | SU122 44 | ussr:R89_SU122_44 | Turret rotator | Retained by standard eligibility checks |
| USSR | ISU130 | ussr:R111_ISU130 | Turret rotator | Retained by standard eligibility checks |
| USSR | ISU122C Berlin | ussr:R116_ISU122C_Berlin | Turret rotator | Retained by standard eligibility checks |
| USSR | M4 Loza | ussr:R140_M4_Loza | Turret rotator | Retained by standard eligibility checks |
| USSR | ISU-152 IGR | ussr:R47_ISU-152_IGR | Turret rotator | Nonstandard battle entry |
| USSR | SU-152 IGR | ussr:R18_SU-152_IGR | Turret rotator | Nonstandard battle entry |
| USSR | SU76I bootcamp | ussr:R50_SU76I_bootcamp | Turret rotator | Nonstandard battle entry |

## 7. Reporting

Similar display names can identify different definitions. Preserve the nation prefix and full ID when reporting. Crew geometry, internal hit geometry and incorrect module HP are separate issues. Describe the impact position, shell/fall/fire cause and actual damage.

A shot at an apparent rack position not damaging it is not alone proof of a bad layout: the actual hit part, penetration path, remaining module HP and settlement also matter. Reproduce through the diagnostic entrance and submit the full report rather than changing a model after one non-damaging hit.

This list does not edit saves, unlock excluded vehicles or replace layouts. Regenerate it against future data rather than carrying forward these counts.

Source checks: read-only audit_internal_layouts.py scan of the supported scripts.pkg, internal_hit_layouts.py, internal_layout_console.py, internal_layout_profiles.py and current eligibility tables.
