"""
Places, companies and topics used by news_collector.py to tag stories.

Edit freely: every list here is plain data. Patterns are case-insensitive regular expressions unless
the entry sits in CASE_SENSITIVE (short tokens like "US" or "EU" that would otherwise match ordinary words).
"""

# country: (region, lat, lon) — lat/lon is where the globe draws the country's news pin
COUNTRIES = {
    "Taiwan": ("East Asia", 23.7, 121.0),
    "South Korea": ("East Asia", 36.5, 127.9),
    "Japan": ("East Asia", 36.2, 138.3),
    "China": ("East Asia", 35.0, 104.0),
    "North Korea": ("East Asia", 40.0, 127.0),
    "Singapore": ("Southeast Asia", 1.35, 103.8),
    "Malaysia": ("Southeast Asia", 4.2, 102.0),
    "Vietnam": ("Southeast Asia", 16.0, 107.8),
    "Thailand": ("Southeast Asia", 15.9, 100.9),
    "Philippines": ("Southeast Asia", 12.9, 121.8),
    "Indonesia": ("Southeast Asia", -2.5, 118.0),
    "Myanmar": ("Southeast Asia", 21.9, 95.9),
    "India": ("South Asia", 21.0, 78.0),
    "Qatar": ("Middle East", 25.3, 51.2),
    "Israel": ("Middle East", 31.0, 34.9),
    "Iran": ("Middle East", 32.4, 53.7),
    "Saudi Arabia": ("Middle East", 23.9, 45.1),
    "United Arab Emirates": ("Middle East", 23.4, 53.8),
    "Turkey": ("Middle East", 39.0, 35.2),
    "European Union": ("Europe", 50.85, 4.35),
    "Netherlands": ("Europe", 52.1, 5.3),
    "Germany": ("Europe", 51.2, 10.4),
    "France": ("Europe", 46.6, 2.4),
    "United Kingdom": ("Europe", 54.0, -2.0),
    "Ireland": ("Europe", 53.4, -8.0),
    "Italy": ("Europe", 42.8, 12.6),
    "Belgium": ("Europe", 50.6, 4.5),
    "Switzerland": ("Europe", 46.8, 8.2),
    "Poland": ("Europe", 52.0, 19.4),
    "Ukraine": ("Europe", 48.4, 31.2),
    "Russia": ("Russia & Central Asia", 55.8, 37.6),
    "Kazakhstan": ("Russia & Central Asia", 48.0, 67.0),
    "United States": ("North America", 39.0, -98.0),
    "Canada": ("North America", 56.0, -106.0),
    "Mexico": ("Latin America", 23.6, -102.5),
    "Brazil": ("Latin America", -14.2, -51.9),
    "Chile": ("Latin America", -35.7, -71.5),
    "Costa Rica": ("Latin America", 9.7, -83.8),
    "Algeria": ("Africa", 28.0, 1.7),
    "South Africa": ("Africa", -30.6, 22.9),
    "DR Congo": ("Africa", -4.0, 21.8),
    "Australia": ("Oceania", -25.3, 133.8),
}

# Words that point to a country: names, demonyms, capitals, chip cities and sites
PLACE_PATTERNS = {
    "Taiwan": [r"taiwan\w*", r"taipei", r"hsinchu", r"tainan", r"kaohsiung", r"taichung", r"台灣", r"台積電"],
    "South Korea": [r"south korea\w*", r"(?<!north )korea(n|'s)?\b", r"seoul", r"pyeongtaek", r"icheon", r"yongin",
                    r"cheongju", r"한국", r"삼성"],
    "North Korea": [r"north korea\w*", r"pyongyang"],
    "Japan": [r"japan\w*", r"tokyo", r"kumamoto", r"hokkaido", r"yokkaichi", r"日本"],
    "China": [r"china", r"chinese", r"beijing", r"shanghai", r"shenzhen", r"wuhan", r"hefei", r"hong kong", r"中国", r"中國"],
    "Singapore": [r"singapore\w*"],
    "Malaysia": [r"malaysia\w*", r"penang", r"kulim", r"johor"],
    "Vietnam": [r"vietnam\w*", r"bac ninh", r"hanoi"],
    "Thailand": [r"thailand", r"\bthai\b"],
    "Philippines": [r"philippine\w*", r"manila"],
    "Indonesia": [r"indonesia\w*"],
    "Myanmar": [r"myanmar", r"kachin"],
    "India": [r"india\b", r"indian", r"dholera", r"gujarat", r"new delhi", r"bengaluru"],
    "Qatar": [r"qatar\w*", r"ras laffan", r"doha"],
    "Israel": [r"israel\w*", r"kiryat gat"],
    "Iran": [r"\biran\w*", r"tehran", r"strait of hormuz", r"hormuz"],
    "Saudi Arabia": [r"saudi"],
    "United Arab Emirates": [r"\buae\b", r"emirati", r"abu dhabi", r"dubai"],
    "Turkey": [r"turkey\b", r"turkish", r"türkiye"],
    "European Union": [r"european union", r"european commission", r"brussels", r"eu chips act"],
    "Netherlands": [r"netherlands", r"dutch", r"veldhoven", r"eindhoven", r"the hague"],
    "Germany": [r"germany", r"german\b", r"dresden", r"magdeburg", r"berlin"],
    "France": [r"france", r"french\b", r"grenoble", r"paris"],
    "United Kingdom": [r"united kingdom", r"\bbritain", r"british", r"london"],
    "Ireland": [r"ireland", r"irish", r"leixlip"],
    "Italy": [r"\bitaly", r"italian"],
    "Belgium": [r"belgi\w+", r"leuven"],
    "Switzerland": [r"switzerland", r"swiss", r"geneva", r"davos"],
    "Poland": [r"poland", r"polish"],
    "Ukraine": [r"ukrain\w*", r"odesa", r"kyiv"],
    "Russia": [r"russia\w*", r"moscow", r"kremlin"],
    "Kazakhstan": [r"kazakh\w*"],
    "United States": [r"united states", r"u\.s\.", r"\bamerican?\b(?! (?:samoa))", r"washington", r"white house",
                      r"commerce department", r"(?<!eu )chips act", r"arizona", r"texas", r"ohio", r"new york", r"oregon",
                      r"idaho", r"silicon valley", r"california"],
    "Canada": [r"canada", r"canadian"],
    "Mexico": [r"mexic\w+", r"guadalajara"],
    "Brazil": [r"brazil\w*"],
    "Chile": [r"\bchile\b", r"chilean"],
    "Costa Rica": [r"costa rica"],
    "Algeria": [r"algeria\w*"],
    "South Africa": [r"south africa\w*"],
    "DR Congo": [r"congo"],
    "Australia": [r"australia\w*", r"mount weld"],
}
# Uppercase-only tokens (matched case-sensitively)
CASE_SENSITIVE = {
    "United States": [r"\bUS\b", r"\bUSA\b"],
    "European Union": [r"\bEU\b"],
    "United Kingdom": [r"\bUK\b"],
}
# Removed before matching so they don't count as countries
STRIP = [r"war department", r"department of war", r"latin america", r"south america", r"north america", r"central america", r"bank of america",
         r"american express", r"applied materials"]

# Company -> home country. Counted as a place mention, weighted lower than a country name.
COMPANIES = {
    "Taiwan": ["TSMC", "UMC", "MediaTek", "Foxconn", "Hon Hai", "ASE Technology", "ASE Group", "GlobalWafers",
               "Powerchip", "PSMC", "Nanya", "Winbond", "Quanta", "Wistron"],
    "South Korea": ["Samsung", "SK hynix", "SK Hynix", "SK Siltron", "Soulbrain"],
    "Japan": ["Tokyo Electron", "Rapidus", "Kioxia", "Shin-Etsu", "SUMCO", "Renesas", "Advantest", "Screen Holdings",
              "Lasertec", "Stella Chemifa", "Morita Chemical", "JSR"],
    "China": ["SMIC", "Huawei", "HiSilicon", "YMTC", "CXMT", "Hua Hong", "Naura", "AMEC", "Do-Fluoride"],
    "United States": ["Intel", "Nvidia", "NVIDIA", "AMD", "Micron", "Qualcomm", "Broadcom", "Applied Materials",
                      "Lam Research", "KLA", "GlobalFoundries", "Texas Instruments", "MP Materials", "Wolfspeed",
                      "Hemlock", "Air Products"],
    "Netherlands": ["ASML", "NXP", "ASM International"],
    "Germany": ["Infineon", "Zeiss", "Wacker", "Bosch", "Siltronic"],
    "France": ["Soitec", "Air Liquide"],
    "Switzerland": ["STMicroelectronics", "STMicro"],
    "United Kingdom": ["Arm Holdings", r"\bArm\b"],
    "Israel": ["Tower Semiconductor"],
    "Australia": ["Lynas"],
    "Qatar": ["QatarEnergy"],
    "India": ["Tata Electronics"],
    "Ukraine": ["Ingas", "Cryoin"],
}

# Is this story about chips at all? Need at least one core hit (title or summary).
CORE = [r"semiconductor\w*", r"\bchips?\b",
        r"chipmak\w+", r"foundr(?:y|ies)\b", r"\bwafers?\b", r"\bfabs?\b", r"lithograph\w*", r"\bEUV\b", r"\bHBM\d?\b",
        r"\bDRAM\b", r"\bNAND\b", r"\bgallium\b", r"\bgermanium\b", r"rare[- ]earths?", r"\bhelium\b",
        r"\bneon\b(?! sign)", r"hydrogen fluoride", r"polysilicon", r"\bTSMC\b", r"\bASML\b", r"\bSMIC\b",
        r"SK hynix", r"반도체", r"半導體", r"半導体", r"halbleiter", r"晶片", r"芯片"]
# Phrases removed before any matching (false friends of "chip" and "fab")
EXCLUDE = [r"potato chips?", r"poker chips?", r"chocolate chips?", r"blue[- ]chip", r"chip and pin",
           r"\bfabric", r"fab four"]

# Headlines dropped as filler: market-research press releases and stock-pick listicles
JUNK = [r"market (?:forecast|size|report|analysis|outlook|share|research)\b.*20[3-4]\d", r"\bCAGR\b",
        r"market to (?:reach|hit|grow)", r"better buy", r"stocks? to (?:watch|buy)", r"should you buy",
        r"top \d+ .*stocks", r"price prediction"]

# topic -> patterns (a story can have several)
TOPICS = {
    "export controls & sanctions": [r"出口管制", r"出口管控", r"수출\s?통제", r"수출\s?규제", r"輸出規制", r"輸出管理", r"制裁", r"제재", r"exportkontroll\w*", r"sanktion\w*", r"exportbeperking\w*", r"export (?:control|ban|curb|restriction|rule|licen[cs])\w*", r"entity list",
                                    r"sanction\w*", r"blacklist\w*"],
    "tariffs & trade": [r"關稅", r"关税", r"관세", r"関税", r"貿易戰", r"贸易战", r"통상", r"zölle?\b", r"zoll\w*", r"handelskrieg", r"heffing\w*", r"tariff\w*", r"section 232", r"trade (?:war|deal|talks|deficit)", r"duties\b", r"customs"],
    "critical materials": [r"稀土", r"희토류", r"レアアース", r"氦", r"헬륨", r"ヘリウム", r"鎵", r"镓", r"갈륨", r"ガリウム", r"鍺", r"锗", r"게르마늄", r"氖", r"네온", r"ネオン", r"氟化氫", r"氟化氢", r"불화수소", r"フッ化水素", r"seltene erden", r"rohstoff\w*", r"rare[- ]earths?", r"\bgallium\b", r"\bgermanium\b", r"\bhelium\b", r"\bneon\b",
                           r"hydrogen fluoride", r"polysilicon", r"\bquartz\b", r"tungsten", r"antimony", r"cobalt",
                           r"critical minerals?"],
    "fabs & capacity": [r"晶圓廠", r"晶圆厂", r"工廠", r"工厂", r"產能", r"产能", r"設廠", r"建廠", r"擴產", r"공장", r"팹", r"증설", r"생산능력", r"工場", r"増産", r"生産能力", r"新工場", r"werk\b", r"fabrik\w*", r"produktionskapazit\w*", r"fabriek\w*", r"\bfabs?\b", r"new (?:plant|factory)", r"capacity", r"capex", r"capital spending",
                        r"groundbreaking", r"megafab", r"production line", r"\bnodes?\b", r"\b[1-9]\s?nm\b", r"chip plants?", r"wafer capacity"],
    "investment & expansion": [r"invest\w*", r"expan\w+", r"\$\s?\d[\d.,]*\s?(?:billion|million|bn|b)\b", r"\bloans?\b",
                               r"\bplants?\b", r"\bhubs?\b", r"cent(?:er|re)\b", r"funding", r"\bdeal\b", r"투자", r"投資", r"投资",
                               r"擴大", r"拡大", r"设厂", r"investition\w*", r"investering\w*"],
    "supply chains & strategy": [r"supply chains?", r"de-?risk\w*", r"reshor\w+", r"diversif\w+", r"self-sufficien\w+",
                                 r"value chain", r"ecosystem", r"stranglehold", r"chokepoint\w*", r"供應鏈", r"供应链", r"공급망",
                                 r"供給網", r"サプライチェーン", r"lieferkette\w*", r"toeleveringsketen\w*", r"생태계"],
    "AI & memory demand": [r"人工智慧", r"人工智能", r"記憶體", r"内存", r"存储", r"메모리", r"인공지능", r"メモリ", r"生成AI", r"rechenzentr\w*", r"\bAI\b", r"\bHBM\d?\b", r"\bDRAM\b", r"\bNAND\b", r"data cent(?:er|re)s?", r"\bGPUs?\b",
                           r"memory prices?"],
    "equipment & lithography": [r"曝光機", r"光刻", r"微影", r"노광", r"장비", r"露光", r"製造装置", r"lithografie", r"anlagenbau", r"lithograph\w*", r"\bEUV\b", r"\bDUV\b", r"chipmaking (?:tools|equipment)",
                                r"etch\w*", r"deposition"],
    "markets & earnings": [r"營收", r"营收", r"財報", r"财报", r"股價", r"股价", r"獲利", r"实绩", r"매출", r"실적", r"주가", r"영업이익", r"決算", r"売上", r"株価", r"umsatz", r"gewinn\w*", r"aktie\w*", r"omzet", r"winst", r"earnings", r"revenue", r"quarterly", r"guidance", r"\bshares\b", r"stock (?:price|market)s?",
                           r"market cap", r"profit\w*", r"\bsales\b", r"valuation"],
    "policy & subsidies": [r"補助", r"补贴", r"政策", r"법안", r"특별법", r"보조금", r"지원", r"補助金", r"経済産業省", r"förder\w*", r"subventio\w*", r"subsidie\w*", r"chips act", r"subsid\w+", r"incentive\w*", r"grants?\b", r"industrial policy",
                           r"legislat\w+", r"\bbill\b", r"ministry", r"government"],
    "conflict & disruption": [r"短缺", r"斷供", r"断供", r"停工", r"停產", r"停产", r"(?<!貿易)戰爭(?!部)", r"(?<!贸易)战争(?!部)", r"차질", r"(?<!무역 )(?<!무역)전쟁", r"공급난", r"不足", r"供給停止", r"戦争", r"engpass\w*", r"lieferstopp", r"krieg\b", r"tekort\w*", r"shortage\w*", r"disrupt\w*", r"outage", r"force majeure", r"\bhalt\w*",
                              r"shut(?:s|down)?\b", r"earthquake", r"\bfire\b", r"strike\w*", r"blockade",
                              r"invasion", r"(?<!trade )(?<!price )(?<!talent )(?<!chip )\bwar\b", r"drone", r"missile", r"conflict", r"smoke", r"explosion", r"\bblast\b", r"casualt\w*", r"evacuat\w*",
                              r"flood\w*", r"blackout", r"power (?:cut|outage)", r"\bleak\w*", r"화재", r"火災", r"火災", r"爆炸", r"停電", r"停电", r"정전"],
}

# Inputs the risk engine tracks -> a story naming one is linked to that input's risk alerts on the globe
TRACKED_INPUTS = {
    "helium": [r"\bhelium\b", r"氦", r"헬륨", r"ヘリウム"],
    "neon": [r"\bneon\b(?! sign)", r"氖", r"네온", r"ネオン"],
    "hydrogen fluoride": [r"hydrogen fluoride", r"hydrofluoric", r"\bHF\b", r"氟化氫", r"氟化氢", r"불화수소", r"フッ化水素"],
    "gallium": [r"\bgallium\b", r"\bGaN\b", r"\bGaAs\b", r"鎵", r"镓", r"갈륨", r"ガリウム"],
}
