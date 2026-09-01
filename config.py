"""
Configuration for the APAC Offshore Wind News Monitor.

Edit this file to add/remove sources, keywords, or markets.
No API keys or passwords live here — those are set as GitHub Secrets
(see README.md).
"""

# ---------------------------------------------------------------------------
# MARKETS
# ---------------------------------------------------------------------------
# Each market has:
#   - "feeds": direct RSS feeds from trade press / local outlets
#   - "gnews_queries": Google News RSS search queries (query, language, country) —
#     no API key needed, and lets us target native-language coverage directly
#   - "native_keywords": local-language keywords, since English-only filters
#     miss a lot of native-language coverage

MARKETS = {
    "Taiwan": {
        "feeds": [
            "https://focustaiwan.tw/rss/business",
            "https://www.taipeitimes.com/xml/index.rss",
        ],
        "gnews_queries": [
            ("offshore wind Taiwan", "en", "TW"),
            ("Taiwan offshore wind auction", "en", "TW"),
            ("離岸風電", "zh-Hant", "TW"),
        ],
        "native_keywords": ["離岸風電", "風力發電", "安裝船", "風場", "經濟部能源署"],
    },
    "Japan": {
        "feeds": [
            "https://www.japantimes.co.jp/feed/",
            "https://www3.nhk.or.jp/rss/news/cat5.xml",  # NHK business
        ],
        "gnews_queries": [
            ("offshore wind Japan", "en", "JP"),
            ("Japan offshore wind auction", "en", "JP"),
            ("洋上風力", "ja", "JP"),
        ],
        "native_keywords": ["洋上風力", "風力発電", "設置船", "経済産業省"],
    },
    "Korea": {
        "feeds": [
            "https://www.koreaherald.com/rss/020000000000.xml",
        ],
        "gnews_queries": [
            ("offshore wind Korea", "en", "KR"),
            ("Korea offshore wind auction", "en", "KR"),
            ("해상풍력", "ko", "KR"),
        ],
        "native_keywords": ["해상풍력", "설치선", "한국전력"],
    },
    "China": {
        "feeds": [
            "https://www.scmp.com/rss/91/feed",  # SCMP China business
        ],
        "gnews_queries": [
            ("offshore wind China", "en", "CN"),
            ("China offshore wind installation vessel", "en", "CN"),
            ("海上风电", "zh-Hans", "CN"),
        ],
        "native_keywords": ["海上风电", "安装船", "风电场"],
    },
    "Vietnam": {
        "feeds": [
            "https://e.vnexpress.net/rss/business.rss",
            "https://vietnamnews.vn/rss/economy.rss",
        ],
        "gnews_queries": [
            ("offshore wind Vietnam", "en", "VN"),
            ("điện gió ngoài khơi", "vi", "VN"),
        ],
        "native_keywords": ["điện gió ngoài khơi", "điện gió"],
    },
    "Philippines": {
        "feeds": [
            "https://www.bworldonline.com/feed/",
            "https://business.inquirer.net/feed",
        ],
        "gnews_queries": [
            ("offshore wind Philippines", "en", "PH"),
        ],
        "native_keywords": [],
    },
    "Australia": {
        "feeds": [
            "https://reneweconomy.com.au/feed/",
            "https://www.abc.net.au/news/feed/51892/rss.xml",  # ABC business
        ],
        "gnews_queries": [
            ("offshore wind Australia", "en", "AU"),
            ("Australia offshore wind auction", "en", "AU"),
        ],
        "native_keywords": [],
    },
}

# ---------------------------------------------------------------------------
# PAN-APAC / GLOBAL TRADE PRESS
# ---------------------------------------------------------------------------
GLOBAL_TRADE_FEEDS = [
    "https://www.rechargenews.com/rss",
    "https://www.upstreamonline.com/rss",
    "https://www.windpowermonthly.com/rss/latest",
    "https://www.offshorewind.biz/feed/",
    "https://gcaptain.com/feed/",
    "https://www.windtech-international.com/rss.xml",
    "https://www.reuters.com/arc/outboundfeeds/v3/rss/category/business/energy/?outputType=xml",
    "https://www.rigzone.com/news/rss/rigzone_latest.aspx",
]

# ---------------------------------------------------------------------------
# KEYWORDS
# ---------------------------------------------------------------------------
CORE_KEYWORDS = [
    "offshore wind", "wind turbine installation vessel", "WTIV", "jack-up vessel",
    "jackup vessel", "foundation installation", "monopile", "floating offshore wind",
    "offshore wind auction", "offshore wind tender", "local content requirement",
    "offshore wind PPA", "offshore wind farm",
]

WATCH_ENTITIES = [
    "Cadeler", "Ørsted", "Orsted", "CIP", "Copenhagen Infrastructure Partners",
    "DEME", "Van Oord", "Seaway7", "Jan De Nul", "Boskalis", "Fred. Olsen",
    "COSCO Shipping Offshore", "Hanwha Ocean", "Samsung Heavy Industries",
    "Vestas", "Siemens Gamesa", "Mingyang", "GE Vernova",
    "Taipower", "JERA", "Mitsubishi", "KEPCO", "Korea Offshore Wind",
    "PetroVietnam", "AC Energy", "AboitizPower", "Star of the South",
]

VESSEL_CONTRACT_KEYWORDS = [
    "installation vessel", "WTIV", "jack-up", "jackup", "newbuild vessel",
    "vessel order", "vessel delivery", "vessel charter", "shipyard",
    "installation contract", "T&I contract", "transport and installation",
]

# ---------------------------------------------------------------------------
# FILTER SETTINGS
# ---------------------------------------------------------------------------
LOOKBACK_DAYS = 7
MAX_ARTICLES_PER_MARKET = 15       # candidates considered before classification
MIN_RELEVANCE_FOR_DIGEST = 2       # 0-3 scale; raise this to show fewer, higher-bar items
MAX_ITEMS_PER_MARKET = 4           # cap shown per market section, after classification
MIN_ITEMS_PER_MARKET = 2           # always show at least this many per market if any news exists at all
MAX_TOP_LINE_ITEMS = 6             # cap on the "top-line summary" section

# ---------------------------------------------------------------------------
# SOURCE CREDIBILITY
# ---------------------------------------------------------------------------
# Domains considered high-credibility trade press / established outlets.
# Used only as a sort tiebreaker (higher relevance always wins first) — helps
# surface a Reuters/Nikkei/Recharge story over a lesser-known aggregator
# when both scored the same relevance.
TRUSTED_DOMAINS = [
    "reuters.com", "bloomberg.com", "nikkei.com", "japantimes.co.jp",
    "focustaiwan.tw", "taipeitimes.com", "koreaherald.com", "yonhapnews.co.kr",
    "vnexpress.net", "vietnamnews.vn", "reneweconomy.com.au", "afr.com",
    "abc.net.au", "scmp.com", "nhk.or.jp", "bworldonline.com",
    "business.inquirer.net", "rigzone.com",
    "rechargenews.com", "upstreamonline.com", "windpowermonthly.com",
    "offshorewind.biz", "gcaptain.com", "windtech-international.com",
]

# ---------------------------------------------------------------------------
# DISPLAY
# ---------------------------------------------------------------------------
MARKET_FLAGS = {
    "Taiwan": "🇹🇼",
    "Japan": "🇯🇵",
    "Korea": "🇰🇷",
    "China": "🇨🇳",
    "Vietnam": "🇻🇳",
    "Philippines": "🇵🇭",
    "Australia": "🇦🇺",
    "Global/APAC": "🌏",
}
