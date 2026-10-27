# 车辆配装、配弹与BOT切弹策略说明

适用版本：1.0.0；支持客户端：中国区高清版《坦克世界》0.9.22.0.1 #1513。

## 一、三类配置分别控制什么

车辆研发配置决定安装哪套履带、发动机、炮塔、火炮等模块；配件、指令、给养和成员决定合法装配下的能力；弹药策略决定装哪些弹及何时切弹。这三类设置可以独立配置。

“车辆白名单”在本文指特定车辆的优选火炮表；“火炮白名单”指特定武器的弹种策略表。它们不决定车辆能否参加对局，也不是自行火炮车型的可用车辆清单。对局可用性见第6份说明。

## 二、研发、配件、给养和成员

研发配置有白板、中间配置、完全体。安装顺序遵守客户端模块兼容、炮塔与火炮组合、承载及配件安装检查；不能仅按模块名称大小选取。完全体优选火炮的特殊车辆列在附表一。

配件有四种模式：无配件、1配件、3普通配件、3紫色配件＋对应指令。实际配件从该车合法配置中取得；白板研发配置只允许无配件。

给养有无给养、小急救包＋小修理箱＋手动灭火器一次、小给养重复使用、大急救包＋大修理箱＋自动灭火器重复使用四种模式。

成员有50%、75%、100%满修理满隐蔽、100%全部满技能四种配置。全技能按车辆实际席位和兼职职责筛选有效技能，不是给所有席位硬塞同样13个技能。

这些设置作用于BOT。默认全解锁存档的玩家车辆另有三件合法紫色配件、对应指令及全技能成员初始配置；玩家保存自己的调整后，不会在每次启动时重新覆盖。

## 三、默认配弹

未填写手动弹药比例时，先确定实际安装火炮可用的主弹、后备弹及高爆弹，再分配库存。附表二中的武器使用指定弹种组合；其他武器按价格类别、弹种类型及原始顺序整理。

| 情况 | 默认比例 |
| --- | --- |
| 普通炮，主弹／增强弹／HE三种 | 60／30／10 |
| 普通炮，仅两种非HE弹 | 60／40 |
| 普通炮，两种弹中包含HE | 80／20 |
| HE主炮，HE主弹＋一种非HE后备弹 | 80／20 |
| 单发自行火炮，普通HE＋增强HE | 80／20 |
| 弹夹自行火炮，普通HE＋增强HE | 75／25 |
| 仅一种有效弹种 | 全部装该弹种 |

自行火炮默认只选HE，不自动把AP作为另一种默认后备弹。只有一种HE时全部装这一种；增强HE必须是该炮真实拥有的弹种。

比例是分配权重，不是每辆车都能得到完全相同的整数百分比。单发炮按发分配；弹夹炮按完整弹夹分配，余数归主弹，不扩大原生弹夹。库存足够时，每种有效选择至少分到一个分配单位；容量过小时优先主弹。例如总共只有1发时，不会为了满足三个比例变成3发。

## 四、手动配弹与携弹数量

在“Bot战术 → 行为参数”中设置弹药比例。每一项为0—9的整数权重，0表示不分配这一种；全部为0表示彻底不携弹。控件顺序按实际弹药排序，不能将三项机械理解成所有车统一的AP／APCR／HE。

手动比例替代默认弹种筛选，可明确选择安装火炮实际支持的弹种。不存在的弹种不会被创造出来。

携弹数量上限可继承原容量，也可设为0—1800的整数；实际携弹不超过车辆本来的容量。0为无弹，1为总共一发，不是每种弹各一发。该设置不修改玩家库存或车辆原生容量。

弹夹暂空、正在装填、当前弹种为0但其他弹种仍有库存，均不等于彻底无弹。彻底无弹后的行动见第3份说明。

## 五、BOT切弹触发

切弹依据真实已发射炮弹的结算结果，不依据瞄准动画或预测伤害。下表按默认弹种组合说明；若手动重配了弹种，则按当前实际有效的弹种阶段执行，不会额外生成增强HE。

| 类型 | 计入失败的结果 | 默认触发 |
| --- | --- | --- |
| 普通主炮 | 命中但没有造成生命值伤害 | 累计两次后尝试下一阶段可用弹种 |
| HE主炮 | 直接命中但未击穿 | 累计两次后尝试指定非HE后备弹 |
| 自行火炮 | 既未命中也未造成伤害 | 累计两次后尝试有库存的增强HE |
| 一次扳机发射多枚炮弹 | 汇总本次扳机实际发出的一组炮弹后，按上述对应类别判定失败 | 一次失败组即可触发 |

普通炮有效伤害清除失败累计；单纯打空不计作零伤害命中。HE主炮以直接击穿作为成功，溅射不当作直接命中。自行火炮命中或造成溅射伤害都会清除失败累计。

更换目标，或相对本轮判定起点水平位移超过3米时重新累计；原地转向及3米内反复活动不会反复刷新。弹夹的失败累计不跨弹夹沿用。结果未知会清除失败累计；旧目标或旧位置的迟到结果不混入新一轮。

只有一种有效弹药或后备弹耗尽时，不能切到不存在的库存。增强HE耗尽后，火炮继续使用剩余可用HE。

## 六、返回主弹与装填衔接

- 弹夹炮：实际打完整个后备弹夹后返回主弹；若失败结果已要求继续切到下一阶段，先执行该决定。
- 单发HE主炮：实际发射一发非HE试探弹后返回主弹。
- 单发自行火炮：实际发射两发增强HE后返回仍有库存的主HE。
- 普通单发炮切到HE阶段：实际发射两发后返回主弹。
- 普通单发炮换用非HE增强弹：不会仅因一次有效伤害立即切回；继续依结果和库存判断。

决定切弹本身不扣弹、不凭空补弹、不重启装填计时。实际换弹由装填和弹夹衔接执行；已经发射的炮弹不因之后切弹而改变弹种或取消结算。

## 七、附表一：车辆优选火炮白名单

下表用于优选模块安装，不表示白板或中间配置一律强制安装该炮。启动器明确选择的研发配置按实际生效规则处理。表中保留资源标识，便于区分同名、季节或旧版本车辆。

共33辆。

| 国家 | 车辆 | 车辆标识 | 优选火炮 | 火炮标识 |
| --- | --- | --- | --- | --- |
| 中国 | T-34-2 | china:Ch05_T34_2 | 100mm 59-100T | _100mm_59-100T |
| 法国 | S-35 CA | france:F33_S_35CA | 105 mm 1930S AC | Canon_de_105_mle_1930_Schneider_AC |
| 德国 | "追猎者" | germany:G09_Hetzer | 10.5 cm StuH 42 L/28 | _105mm_StuH42_L28 |
| 德国 | 克虏伯试验车 | germany:G100_Gtraktor_Krupp | 7.5 cm KwK 37 L/24 | _75mm_KwK_37_L24A |
| 德国 | III号突击炮B型 | germany:G101_StuG_III | 10.5 cm StuH 42 L/28 | _105mm_StuH42_L28 |
| 德国 | IV号H型 | germany:G81_Pz_IV_AusfH | 10.5 cm KwK 42 L/28 | _105mm_StuH42_L28Pz |
| 德国 | IV号A型 | germany:G83_Pz_IV_AusfA | 7.5 cm KwK 37 L/24 | _75mm_KwK_37_L24 |
| 德国 | IV WT | germany:G97_Waffentrager_IV | 12.8 cm K44/2 L/61 | _128mm_K44_2_L61 |
| 德国 | Rhm·B WT | germany:G99_RhB_Waffentrager | 12.8 cm K44 L/55 | _128mm_K44_L55 |
| 日本 | 五式重战 | japan:J20_Type_2605 | 15cm/45 四一年式 | _150mm_45_41st_Year_Type |
| 日本 | 120吨试验型 | japan:J23_Mi_To | 12cm 短管炮 | _120mm_Short_Barrel_Gun |
| 日本 | 120吨I型 | japan:J24_Mi_To_130_tons | 15cm 九六式 | _150mm_Howitzer_Type96 |
| 日本 | 四式重战 | japan:J25_Type_4 | 15cm/45 四一年式 | _150mm_45_41st_Year_Type |
| 日本 | 120吨V型 | japan:J27_O_I_120 | 15cm 九六式 | _150mm_Howitzer_Type96 |
| 日本 | 120吨IV型 | japan:J28_O_I_100 | 15cm 九六式 | _150mm_Howitzer_Type96 |
| 瑞典 | SM-43 | sweden:S19_Sav_M43 | 10.5cm M44 sav | _105mm_kan_m_44_sav |
| 英国 | 百夫长 Mk.VII | uk:GB24_Centurion_Mk3 | 105 mm RO L7A1 | _105mm_Gun_L7 |
| 英国 | FV215b (183) | uk:GB48_FV215b_183 | 183 mm L4 | _183mm_L4 |
| 英国 | AT 15 | uk:GB72_AT15 | 32磅反坦克炮 | _32-pounder_AT_Gun_OQF |
| 英国 | 御夫座 | uk:GB80_Charioteer | 105 mm L7 AT | _105mm_AT_Gun_L7 |
| 英国 | FV4004 康威 | uk:GB81_FV4004 | BL 5.5英寸 | _5_5inch_AT_Gun |
| 英国 | FV4005 | uk:GB83_FV4005 | 183 mm L4 | _183mm_AT_Gun |
| 美国 | T49 | usa:A100_T49 | 152 mm XM81火箭炮 (传统型) | _152mm_Gun_Launcher_M81 |
| 美国 | XM551 谢里登 | usa:A116_XM551 | 152 mm XM81火箭炮 (传统型) | _152mm_Gun_Launcher_M81 |
| 苏联 | KV-85 | ussr:R106_KV85 | 100 mm S-34 | _100mm_S34 |
| 苏联 | ISU-130 | ussr:R111_ISU130 | 130 mm S-26 | _130mm_S-26A |
| 苏联 | A-20 | ussr:R12_A-20 | 45 mm VT-42 | _45mm_VT-42 |
| 苏联 | SU-152 | ussr:R18_SU-152 | 152 mm ML-20 1931/37型 | _152mm_ML-20_mod_1937 |
| 苏联 | T-44 | ussr:R20_T-44 | 100 mm LB-1 | _100mm_LB-1 |
| 苏联 | T-46 | ussr:R22_T-46 | 45 mm VT-42 | _45mm_VT-42 |
| 苏联 | T-80 | ussr:R44_T80 | 45 mm VT-43 | _45mm_VT-43 |
| 苏联 | SU-100Y | ussr:R49_SU100Y | 130 mm B-13-S2 | _130mm_B-13-S2 |
| 苏联 | KV-2 | ussr:R77_KV2 | 152 mm M-10 | _152mm_M-10 |

## 八、附表二：火炮弹种策略白名单

这里的“火炮”指武器模块，包含普通坦克炮和自行火炮用炮。按“国家＋武器标识”匹配，与前一张车辆优选炮表独立；同一门炮安装在另一辆车上，仍按实际安装的炮应用弹种表。

表中第一种是主弹，其后是后备阶段；“主／后备”是策略身份，不保证第一种一定是银币AP、第二种一定是金币弹。HE主炮等特例以表中指定弹种为准。未列出的武器继续使用通用配弹规则。

共43种武器。

| 国家 | 火炮 | 武器标识 | 主弹 | 后备1 | 后备2 |
| --- | --- | --- | --- | --- | --- |
| 中国 | 57mm 97式 | china:_57mm_Gun_Type_97 | 97式 HE（_57mm_HE_Type_97） | 57mm 97式 HEAT（_57mm_HEAT_Type_97） | — |
| 法国 | 105 mm 1934S AC | france:Canon_de_105_court_mle_1934S_AC | OE mle.1920（_105mm_OE_mle_1920） | OCO mle.1936（_105mm_OCO_mle._1936） | — |
| 法国 | 105 mm 1934 | france:Canon_de_105_court_mle_1934S_T | OE mle.1920（_105mm_OE_mle_1920） | OCO mle.1936（_105mm_OCO_mle._1936） | — |
| 法国 | 105 mm leFH18 L28 | france:_105mm_leFH18_L28 | Sprgr.K（_105mm_Sprg_K） | — | — |
| 法国 | 47mm SA34 | france:_47mm_SA34 | OE D型（_47mm_Oe_type_D） | ODR mle.1935 Bref（_47mm_Odr_mle_1935_b） | — |
| 德国 | 10.5 cm StuH 42 L/28 | germany:_105mm_StuH42_L28 | Sprgr K（_105mm_Sprg_K） | Gr 39 H1A（_105mmGr39H1A） | — |
| 德国 | 10.5 cm KwK 42 L/28 | germany:_105mm_StuH42_L28Pz | Sprgr K（_105mm_Sprg_K） | Gr 39 H1A（_105mmGr39H1A） | — |
| 德国 | 7.5 cm KwK 37 L/24 | germany:_75mm_KwK_37_L24 | Sprgr 18（_75mm_Sprg.18） | Gr 38 HL A（_Gr_38_HL_A） | — |
| 德国 | 7.5 cm KwK 37 L/24 | germany:_75mm_KwK_37_L24A | Sprgr 18（_75mm_Sprg.18） | Gr 38 HL A（_Gr_38_HL_A） | — |
| 德国 | 7.5 cm StuK 37 L/24 | germany:_75mm_StuK_37_L24 | Sprgr 18（_75mm_Sprg.18） | Gr 38 HL A（_Gr_38_HL_A） | — |
| 日本 | 12cm 短管炮 | japan:_120mm_Short_Barrel_Gun | HE （_120mm_HE_Commerce_Raid） | HEAT 八八式（_120mm_HEAT_Type_88） | — |
| 日本 | 15cm/45 四一年式 | japan:_150mm_45_41st_Year_Type | 通用0式改（_150mm_Common_Type_0_HE_Kai） | — | — |
| 日本 | 15cm 九六式 | japan:_150mm_Howitzer_Type96 | HE 九六式（_150mm_HE_Type96） | HEAT 九二式（_150mm_HEAT_Type3） | — |
| 日本 | 5.7cm 九零式 | japan:_57mm_Gun_Type90 | 97式 HE（_57mm_HE_Type97） | 57mm 97式 HEAT（_57mm_HEAT_Type97） | — |
| 日本 | 57mm 97式 | japan:_57mm_Gun_Type97 | 97式 HE（_57mm_HE_Type97） | 57mm 97式 HEAT（_57mm_HEAT_Type97） | — |
| 日本 | 7cm 九四式 | japan:_70mm_Gun_Type_94 | HE 92式（_70mm_HE_Type92） | HEAT 九二式（_70mm_HEAT_Type3） | — |
| 瑞典 | 10.5cm M44 sav | sweden:_105mm_kan_m_44_sav | 10.5cm lsm 34（_105mm_lt_sgr_m_34） | 10.5cm prm 49（_105mm_psgr_m_49） | — |
| 英国 | 105 mm L7 AT | uk:_105mm_AT_Gun_L7 | HESH-T L-37（_105mm_HESH_L7） | APDS L-28（_105mm_APCR_L7） | — |
| 英国 | 105 mm RO L7A1 | uk:_105mm_Gun_L7 | HESH-T L-37（_105mm_HESH_L7） | APDS L-28（_105mm_APCR_L7） | — |
| 英国 | 105 mm M4 | uk:_105mm_SPH_M4_L23 | HE M1（_105mm_HE_M1） | HEAT M67（_105mm_HEAT_M67） | — |
| 英国 | 183 mm L4 | uk:_183mm_AT_Gun | HESH Mk.1（_183mm_HESH） | AP Mk.1（_183mm_AP_Mk1） | — |
| 英国 | 183 mm L4 | uk:_183mm_L4 | HESH Mk.1（_183mm_HESH） | AP Mk.1（_183mm_AP_Mk1） | — |
| 英国 | 25磅野炮 | uk:_25pdr_Field_Gun | HE Mk.1D（_25pdr_HE_Mk_1D） | — | — |
| 英国 | 3.7英寸反坦克炮 | uk:_3.7inch_AT_Howitzer | HE Mk.3（_3.7inch_HE_Mk3） | HEAT Mk.1（_3.7inch_HEAT_Mk1） | — |
| 英国 | 3.7英寸 榴弹炮 | uk:_3.7inch_Howitzer | HE Mk.3（_3.7inch_HE_Mk3） | HEAT Mk.1（_3.7inch_HEAT_Mk1） | — |
| 英国 | BL 5.5英寸 | uk:_5_5inch_AT_Gun | HESH Mk.1（_5_5inch_HESH_Mk_1） | AP Mk.1（_5_5inch_AP_Mk_1） | — |
| 英国 | OQF3英寸Mk.I榴弹炮 | uk:_76mm_Howitzer_MkI | HE Mk.I（_76mm_HE_MkI） | HEAT Mk.I（_76mm_HEAT_MkI） | — |
| 美国 | 105 mm AT M3 | usa:_105mm_AT_Howitzer_M3 | HE M1（_105mm_HE_M1） | HEAT M67（_105mm_HEAT_M67） | — |
| 美国 | 105 mm AT M4 | usa:_105mm_AT_SPH_M4_L23 | HE M1（_105mm_HE_M1） | HEAT M67（_105mm_HEAT_M67） | — |
| 美国 | 105 mm M4 | usa:_105mm_SPH_M4_L23 | HE M1（_105mm_HE_M1） | HEAT M67（_105mm_HEAT_M67） | — |
| 美国 | 152 mm XM81火箭炮 (传统型) | usa:_152mm_Gun_Launcher_M81 | HE XM657E3（_152mm_HE_XM657E3） | HEAT XM409（_152mm_HEAT_XM409） | — |
| 美国 | 75 mm ATH M3 | usa:_75mm_AT_Howitzer_M3 | M48（_75mm_M48） | HEAT M66（_75mm_HEAT_M66） | — |
| 美国 | 75 mm ATH M1A1 | usa:_75mm_Howitzer_M1A1 | M48（_75mm_M48） | HEAT M66（_75mm_HEAT_M66） | — |
| 美国 | 75 mm M3 | usa:_75mm_Howitzer_M3 | M48（_75mm_M48） | HEAT M66（_75mm_HEAT_M66） | — |
| 苏联 | 122 mm S-41 | ussr:_122mm_S-41 | OF-420S（_122mm_OF420S） | BP-450A（_122mm_BP450S） | — |
| 苏联 | 122 mm M-30C | ussr:_122mm_cannon_M-30S | OF-420S（_122mm_OF420S） | BP-450A（_122mm_BP450S） | — |
| 苏联 | 122 mm U-11 | ussr:_122mm_cannon_U-11 | OF-420S（_122mm_OF420S） | BP-450A（_122mm_BP450S） | — |
| 苏联 | 130 mm B-13-S2 | ussr:_130mm_B-13-S2 | PB-46А（_130mm_PB-46A） | PB-46（_130mm_PB-46） | OF-46（_130mm_OF-46） |
| 苏联 | 130 mm S-26 | ussr:_130mm_S-26A | Ch.II号-01743（_130mm_2-01743） | Ch.II号-02864A（_130mm_2-02864A） | Ch.II号-02742（_130mm_2-02742） |
| 苏联 | 152 mm M-10 | ussr:_152mm_M-10 | 53-OF-530（_152mm_53-OF-530） | 152 mm 1915/28 MPB（_152mm_MPB_1915） | — |
| 苏联 | 152 mm ML-20 1931/37型 | ussr:_152mm_ML-20_mod_1937 | 53-OF-530（_152mm_53-OF-530） | 53BP540（_152mm_53BP540） | — |
| 苏联 | 76 mm KT-28 | ussr:_76mm_KT-28 | UOF-354K（_76mm_UOF-354K） | BP-350A（_76mm_BP-354） | — |
| 苏联 | 76 mm KT-28 | ussr:_76mm_KT-28A | UOF-354K（_76mm_UOF-354K） | — | — |

核对依据：default_loadouts.py、ammo_policy.py、bot_fittings.py、vehicle_configuration.py，以及当前客户端车辆与武器名称资源。
