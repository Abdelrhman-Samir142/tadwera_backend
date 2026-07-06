"""
Intent Router — Smart Query Classifier + Entity Extractor.

V2 Architecture: Zero-LLM classification AND entity extraction.
Uses keyword matching, regex patterns, and Arabic text normalization.

Intents:
- greeting:     "ازيك" / "أهلا" → instant template response
- faq:          "انت مين" / "ازاي أبيع" → instant FAQ response
- chitchat:     "شكرا" / "تمام" → instant casual response
- search:       "غسالة أقل من 5000 في القاهرة" → full pipeline
- follow_up:    references previous context

Entities extracted (for search intents):
- product:   the item being searched for
- price_min: minimum price constraint
- price_max: maximum price constraint
- location:  city/area filter
- category:  mapped product category
"""

import re
import random
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Arabic Text Normalization
# ═══════════════════════════════════════════════════════════

# Common Arabic letter variations → normalized form
_NORM_MAP = {
    'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا',
    'ة': 'ه',
    'ى': 'ي',
    'ؤ': 'و',
    'ئ': 'ي',
}

_DIACRITICS = re.compile(r'[\u064B-\u065F\u0670]')  # Arabic diacritics (tashkeel)


def normalize_arabic(text: str) -> str:
    """Normalize Arabic text for fuzzy matching."""
    text = _DIACRITICS.sub('', text)  # Remove tashkeel
    for src, dst in _NORM_MAP.items():
        text = text.replace(src, dst)
    return text.strip().lower()


# ═══════════════════════════════════════════════════════════
# Product Search Keywords
# ═══════════════════════════════════════════════════════════

SEARCH_KEYWORDS = [
    # ── أجهزة منزلية (Appliances) ──
    'غسالة', 'غساله', 'تلاجة', 'تلاجه', 'ثلاجة', 'ثلاجه',
    'تكييف', 'تكيف', 'مكيف', 'بوتاجاز', 'فرن', 'كوكر',
    'مكنسة', 'مكنسه', 'سخان', 'فلتر', 'فريزر', 'ديب فريزر',
    'مكواة', 'مكواه', 'خلاط', 'مروحة', 'مروحه', 'دفاية', 'دفايه',
    'أنبوبة', 'انبوبه', 'غاز',

    # ── إلكترونيات (Electronics) ──
    'لابتوب', 'لاب توب', 'لاب', 'موبايل', 'تليفون', 'شاشة', 'شاشه',
    'تلفزيون', 'كمبيوتر', 'طابعة', 'طابعه', 'راوتر',
    'سماعة', 'سماعه', 'سماعات', 'بلايستيشن', 'بلاي ستيشن', 'بلاستيشن',
    'كاميرا', 'ساعة', 'ساعه', 'كيبورد', 'ماوس', 'هارد',
    'فلاشة', 'فلاشه', 'رسيفر', 'سبيكر',
    'دراع', 'دراعات', 'جاك', 'يد تحكم', 'كنترولر', 'controller',
    'iphone', 'samsung', 'hp', 'dell', 'lenovo', 'ps4', 'ps5', 'xbox',
    'playstation', 'جيمنج', 'gaming',

    # ── أثاث (Furniture) ──
    'كنبة', 'كنبه', 'سرير', 'ترابيزة', 'ترابيزه', 'دولاب',
    'نيش', 'سفرة', 'سفره', 'مكتب', 'كرسي', 'ستارة', 'ستاره',
    'مرآة', 'مرايه', 'مراية', 'خزانة', 'خزانه', 'تسريحة', 'تسريحه',
    'أباجورة', 'ابجوره', 'لمبة', 'لمبه', 'خزنة', 'خزنه',

    # ── سيارات وعقارات ──
    'عربية', 'عربيه', 'سيارة', 'سياره', 'شقة', 'شقه',
    'عقار', 'محل', 'أرض', 'ارض', 'فيلا',

    # ── خردة (Scrap) ──
    'خردة', 'خرده', 'حديد', 'نحاس', 'ألومنيوم', 'المونيوم',
    'موتور', 'سلك', 'معدات',

    # ── كتب ──
    'كتاب', 'كتب', 'رواية', 'روايه',

    # ── عام ──
    'مستعمل', 'مستعمله', 'جديد', 'جديده',
]

# ── SQL-Triggering Keywords (structured query needed) ──
SQL_TRIGGER_KEYWORDS = [
    # Price filters
    'أقل من', 'اقل من', 'أكتر من', 'اكتر من', 'أكثر من',
    'ميزانية', 'بادجت', 'budget',
    'ارخص', 'أرخص', 'اغلى', 'أغلى',
    'جنيه', 'ج.م', 'EGP',
    'من', 'لحد', 'لغاية',
    # Numbers (price ranges)
    r'\d{3,}',  # 3+ digit numbers likely prices

    # Sorting
    'أحدث', 'احدث', 'أقدم', 'اقدم',
    'أكتر مشاهدة', 'اكتر مشاهده',
    'ترتيب',

    # Auctions
    'مزاد', 'مزادات', 'auction',

    # Categories
    'فئة', 'فئه', 'category', 'قسم',

    # Location
    'في القاهرة', 'فالقاهره', 'في الإسكندرية', 'فإسكندريه',
    'في المنصورة', 'في طنطا', 'في أسيوط', 'في الجيزة',
    'في المعادي', 'في مدينة نصر', 'في مصر الجديدة',
    'في الزقازيق', 'في بنها', 'في دمنهور', 'في بورسعيد',
    'في السويس', 'في الفيوم', 'في المنيا', 'في سوهاج',
    'في الغردقة', 'في شرم', 'في مرسى مطروح',
]


# ═══════════════════════════════════════════════════════════
# Greeting Patterns & Responses
# ═══════════════════════════════════════════════════════════

GREETING_PATTERNS = [
    r'^(ازيك|إزيك|ازاي|إزاي|عامل ايه|عامل إيه)[\s\.\!\؟]*$',
    r'^(اهلا|أهلا|هلا|يا هلا|اهلاً|أهلاً)[\s\.\!\؟]*$',
    r'^(سلام|سلام عليكم|السلام عليكم)[\s\.\!\؟]*$',
    r'^(هاي|هاى|مرحبا|مرحباً)[\s\.\!\؟]*$',
    r'^(hi|hello|hey|good morning|good evening|yo|sup)[\s\.\!\?]*$',
    r'^(صباح الخير|مساء الخير|صباح النور|مساء النور)[\s\.\!\؟]*$',
    r'^(كيف حالك|كيف الحال|شو اخبارك)[\s\.\!\؟]*$',
]

GREETING_RESPONSES = [
    "أهلاً بيك! 👋 أنا بوت 4Sale الذكي. قولي بتدور على ايه وأنا هساعدك تلاقيه!",
    "يا هلا! 😊 أنا هنا عشان أساعدك تلاقي أي حاجة بتدور عليها. اسأل براحتك!",
    "أهلاً وسهلاً! 🤖 أنا مساعدك في 4Sale. قولي عايز ايه وأنا هدورلك عليه!",
    "مرحباً! ✨ إزيك! أنا البوت الذكي بتاع 4Sale. اكتبلي اللي بتدور عليه!",
]


# ═══════════════════════════════════════════════════════════
# FAQ Patterns & Responses
# ═══════════════════════════════════════════════════════════

FAQ_MAP = {
    # ── About the bot ──
    r'(انت مين|انتو مين|انتا مين|مين انت|ايه الموقع|ايه التطبيق|بتعمل ايه|ايه وظيفتك)':
        "أنا بوت 4Sale الذكي 🤖 بساعدك تلاقي أي حاجة عايز تشتريها أو تبيعها. "
        "اكتبلي اسم المنتج اللي بتدور عليه وأنا هدورلك في كل السوق!",

    # ── How to buy ──
    r'(ازاي|إزاي).*(اشتري|أشتري|اشترى|شراء)':
        "عشان تشتري:\n"
        "1️⃣ دور على المنتج اللي عايزه\n"
        "2️⃣ افتح صفحة المنتج وشوف التفاصيل\n"
        "3️⃣ تواصل مع البائع في الشات\n"
        "4️⃣ اتفقوا على السعر وطريقة التسليم",

    # ── How to sell ──
    r'(ازاي|إزاي).*(ابيع|أبيع|بيع)':
        "عشان تبيع:\n"
        "1️⃣ اضغط على 'أضف منتج' ➕\n"
        "2️⃣ ارفع صور المنتج (الذكاء الاصطناعي هيصنفه تلقائي!)\n"
        "3️⃣ اكتب العنوان والوصف والسعر\n"
        "4️⃣ اختار لو عايز مزاد أو بيع مباشر\n"
        "5️⃣ انشر وستنى المشترين يتواصلوا معاك! 🚀",

    # ── Auctions ──
    r'(ازاي|إزاي).*(المزاد|المزادات|ازايد|أزايد|مزايدة|مزايده)':
        "نظام المزادات:\n"
        "🔹 كل مزاد بيبدأ بسعر افتتاحي\n"
        "🔹 زايد بمبلغ أعلى من المزايدة الحالية\n"
        "🔹 اللي بيكسب هو أعلى مزايد لما الوقت يخلص ⏰\n"
        "🔹 ممكن تفعل الوكيل الذكي يزايد تلقائي عنك! 🤖",

    # ── Smart Agent ──
    r'(الوكيل|الايجنت|agent|الذكي|auto.?bid)':
        "الوكيل الذكي 🤖 ده مساعد بيدور لك على المنتجات تلقائياً!\n"
        "🔹 اختار نوع المنتج اللي عايزه (مثلاً: غسالة)\n"
        "🔹 حدد ميزانيتك القصوى\n"
        "🔹 اكتب شروطك (مثلاً: توشيبا، حالة كويسة)\n"
        "🔹 الوكيل هيلاقيلك المنتج المناسب ويزايد عليه أوتوماتيك! ⚡",

    # ── Wallet ──
    r'(المحفظة|المحفظه|الرصيد|اشحن|فلوس|محفظتي|محفظتى|wallet)':
        "المحفظة 💰 هي اللي بتزايد وتشتري منها:\n"
        "🔹 روح صفحة 'المحفظة' من القائمة\n"
        "🔹 اشحن رصيدك بالمبلغ اللي عايزه\n"
        "🔹 الرصيد بيتخصم تلقائي لما تشتري أو تزايد",

    # ── Visual Search ──
    r'(بحث بصري|بحث بالصورة|صورة|visual.?search)':
        "البحث البصري 📸 يخليك تلاقي منتجات شبه صورة عندك!\n"
        "🔹 ارفع صورة أي منتج\n"
        "🔹 الذكاء الاصطناعي هيلاقيلك منتجات مشابهة في السوق",

    # ── Categories ──
    r'(الاقسام|الأقسام|الفئات|فيه ايه|فيه إيه|بتبيعوا ايه)':
        "الأقسام المتاحة على المنصة:\n"
        "🏠 أثاث وديكور\n"
        "📱 إلكترونيات وأجهزة\n"
        "🏡 أجهزة منزلية\n"
        "🔩 خردة ومعادن\n"
        "🚗 سيارات\n"
        "🏢 عقارات\n"
        "📚 كتب\n"
        "📦 أخرى",

    # ── Safety / Trust ──
    r'(أمان|امان|موثوق|نصب|احتيال|ثقة|ثقه)':
        "نصائح للأمان على المنصة:\n"
        "✅ شوف تقييم البائع قبل الشراء\n"
        "✅ قابل البائع في مكان عام\n"
        "✅ اتأكد من المنتج قبل ما تدفع\n"
        "✅ استخدم الشات الداخلي للتواصل\n"
        "⚠️ متبعتش فلوس مقدم لأي حد",
}


# ═══════════════════════════════════════════════════════════
# Chitchat Patterns & Responses
# ═══════════════════════════════════════════════════════════

CHITCHAT_PATTERNS = {
    r'^(شكرا|شكراً|متشكر|تسلم|الله ينور|يسلمو|thanks|thank you|thx)[\s\.\!\؟]*$': [
        "العفو! 😊 لو محتاج أي حاجة تانية قولي!",
        "ولا يهمك! 🙌 أنا موجود لو محتاج حاجة!",
        "أي خدمة! ✨ بالتوفيق!",
    ],
    r'^(تمام|حلو|جميل|ممتاز|عظيم|رائع|great|nice|cool|ok|أوك|اوك|طيب|ماشي)[\s\.\!\؟]*$': [
        "تمام! 😊 لو عايز تدور على حاجة تانية قولي!",
        "حلو! 🎉 أنا هنا لو محتاج أي حاجة!",
    ],
    r'^(باي|مع السلامة|سلام|bye|goodbye|see you|يلا باي)[\s\.\!\؟]*$': [
        "مع السلامة! 👋 بالتوفيق وارجعلنا تاني!",
        "باي باي! 😊 أي وقت محتاج حاجة أنا موجود!",
        "سلام! 🙌 نورتنا!",
    ],
    r'(هههه|ههه|😂|😁|😆|lol|haha)': [
        "😂😂 لو محتاج حاجة قولي!",
        "هههه 😄 طيب عايز تدور على حاجة؟",
    ],
    r'(❤️|👍|🔥|💪|👏)': [
        "❤️ شكراً! لو محتاج حاجة أنا هنا!",
        "💪 يلا بينا! عايز تدور على ايه؟",
    ],
}


# ═══════════════════════════════════════════════════════════
# Main Classification Function
# ═══════════════════════════════════════════════════════════

def classify_intent(query: str) -> dict:
    """
    Classify user query intent WITHOUT using any LLM.
    
    Returns:
    {
        "intent": "greeting" | "faq" | "chitchat" | "search_full" | "search_light",
        "response": str | None,    # Pre-built response (if no LLM needed)
        "run_sql": bool,           # Whether to run SQL generation
        "run_vector": bool,        # Whether to run vector search
        "run_synthesis": bool,     # Whether to run LLM synthesis
        "tokens_saved": str,       # Estimated tokens saved
    }
    """
    q = query.strip()
    q_normalized = normalize_arabic(q)
    
    # ── 1. Greeting Detection ──────────────────────────
    for pattern in GREETING_PATTERNS:
        if re.search(pattern, q, re.IGNORECASE):
            logger.info(f"[IntentRouter] GREETING detected: '{q[:30]}'")
            return {
                "intent": "greeting",
                "response": random.choice(GREETING_RESPONSES),
                "run_sql": False,
                "run_vector": False,
                "run_synthesis": False,
                "tokens_saved": "~1300 (skipped all LLM calls)",
            }
    
    # ── 2. FAQ Detection ───────────────────────────────
    for pattern, answer in FAQ_MAP.items():
        if re.search(pattern, q, re.IGNORECASE):
            logger.info(f"[IntentRouter] FAQ detected: '{q[:30]}'")
            return {
                "intent": "faq",
                "response": answer,
                "run_sql": False,
                "run_vector": False,
                "run_synthesis": False,
                "tokens_saved": "~1300 (skipped all LLM calls)",
            }
    
    # ── 3. Chitchat Detection ──────────────────────────
    for pattern, responses in CHITCHAT_PATTERNS.items():
        if re.search(pattern, q, re.IGNORECASE):
            logger.info(f"[IntentRouter] CHITCHAT detected: '{q[:30]}'")
            return {
                "intent": "chitchat",
                "response": random.choice(responses),
                "run_sql": False,
                "run_vector": False,
                "run_synthesis": False,
                "tokens_saved": "~1300 (skipped all LLM calls)",
            }
    
    # ── 4. Product Search Detection ────────────────────
    has_search_keyword = any(kw in q for kw in SEARCH_KEYWORDS)
    
    if has_search_keyword:
        # V2: Always run full pipeline (SQL is now fast single-shot)
        logger.info(f"[IntentRouter] SEARCH: '{q[:40]}'")
        return {
            "intent": "search",
            "response": None,
            "run_sql": True,
            "run_vector": True,
            "run_synthesis": True,
            "tokens_saved": "0",
        }
    
    # ── 5. Follow-up Question Detection ────────────────
    # Questions that reference previous results (need chat history + synthesis)
    FOLLOWUP_PATTERNS = [
        r'(مين|منين|بتاع|بتاعه|بتاعهم|بتوعهم)',   # who/whose
        r'(فين|مكانه|عنوانه|موقعه)',                  # where
        r'(كام سعر|سعره كام|بكام|تمنه|ثمنه)',        # price
        r'(حالته|حالتها|حالتهم)',                      # condition
        r'(ورين|وريني|عايز أشوف|أشوفه|أشوفها)',       # show me
        r'(الأول|التاني|التالت|رقم \d)',              # ordinal reference
        r'(أحسن واحد|أحسنهم|أفضل)',                   # best one
        r'(تاني حاجة|حاجة تانية|في غيره)',             # anything else
        r'(أرخص واحد|أرخصهم|أغلاهم)',                 # cheapest/most expensive
        r'(تواصل|أتواصل|رقمه|رقم البائع)',             # contact seller
        r'(مواصفات|تفاصيل)',                          # details/specs
    ]
    
    is_followup = any(re.search(p, q, re.IGNORECASE) for p in FOLLOWUP_PATTERNS)
    
    if is_followup:
        # Follow-up question — needs synthesis with chat history, no new search
        logger.info(f"[IntentRouter] FOLLOW_UP: '{q[:40]}' (references previous results)")
        return {
            "intent": "follow_up",
            "response": None,
            "run_sql": False,
            "run_vector": False,
            "run_synthesis": True,
            "tokens_saved": "~500 (skipped SQL, vector uses history only)",
        }
    
    # ── 6. Fallback: try search ──────────────────────────
    # If we can't classify, still try the full pipeline
    logger.info(f"[IntentRouter] FALLBACK search: '{q[:40]}'")
    return {
        "intent": "search",
        "response": None,
        "run_sql": True,
        "run_vector": True,
        "run_synthesis": True,
        "tokens_saved": "0",
    }


# ═══════════════════════════════════════════════════════════
# Entity Extraction — Zero LLM
# ═══════════════════════════════════════════════════════════

# Location patterns (Egyptian cities and neighborhoods)
_LOCATIONS = [
    'القاهرة', 'القاهره', 'الجيزة', 'الجيزه', 'الإسكندرية', 'اسكندريه', 'الاسكندريه',
    'المنصورة', 'المنصوره', 'طنطا', 'أسيوط', 'اسيوط', 'الزقازيق',
    'بنها', 'دمنهور', 'بورسعيد', 'السويس', 'الفيوم', 'المنيا', 'سوهاج',
    'الغردقة', 'الغردقه', 'شرم الشيخ', 'شرم', 'مرسى مطروح',
    'المعادي', 'المعادى', 'مدينة نصر', 'مدينه نصر', 'مصر الجديدة', 'مصر الجديده',
    'الدقي', 'الدقى', 'المهندسين', 'الهرم', 'فيصل', 'العباسية', 'العباسيه',
    'شبرا', 'عين شمس', 'حلوان', 'التجمع', 'الشروق', 'مدينتي', 'العبور',
    '6 أكتوبر', 'اكتوبر', 'الشيخ زايد', 'زايد',
]

# Category mapping
_CATEGORY_KEYWORDS = {
    'electronics': ['لابتوب', 'لاب', 'موبايل', 'تليفون', 'شاشة', 'شاشه', 'تلفزيون',
                     'كمبيوتر', 'طابعة', 'طابعه', 'سماعة', 'سماعات', 'بلايستيشن',
                     'بلاستيشن', 'كاميرا', 'كيبورد', 'ماوس', 'هارد', 'فلاشة', 'رسيفر',
                     'دراع', 'دراعات', 'جاك', 'كنترولر', 'iphone', 'samsung', 'ps4', 'ps5', 'xbox'],
    'appliances': ['غسالة', 'غساله', 'تلاجة', 'تلاجه', 'ثلاجة', 'تكييف', 'تكيف', 'مكيف',
                    'بوتاجاز', 'فرن', 'مكنسة', 'سخان', 'فلتر', 'فريزر', 'مكواة', 'خلاط',
                    'مروحة', 'مروحه', 'دفاية'],
    'furniture': ['كنبة', 'كنبه', 'سرير', 'ترابيزة', 'ترابيزه', 'دولاب', 'نيش', 'سفرة',
                   'مكتب', 'كرسي', 'انتريه', 'تسريحة'],
    'cars': ['عربية', 'عربيه', 'سيارة', 'سياره'],
    'real_estate': ['شقة', 'شقه', 'عقار', 'محل', 'أرض', 'ارض', 'فيلا'],
    'scrap_metals': ['خردة', 'خرده', 'حديد', 'نحاس', 'ألومنيوم', 'المونيوم'],
    'books': ['كتاب', 'كتب', 'رواية', 'روايه'],
}

# Price patterns
_PRICE_PATTERNS = [
    # "أقل من 5000" / "اقل من 5000"
    (r'(?:أقل|اقل|ارخص|أرخص)\s*(?:من)?\s*(\d[\d,\.]*)', 'max'),
    # "أكتر من 1000" / "اكتر من 1000"
    (r'(?:أكتر|اكتر|أكثر|اغلى|أغلى)\s*(?:من)?\s*(\d[\d,\.]*)', 'min'),
    # "من 1000 لحد 5000" / "من 1000 ل 5000"
    (r'من\s*(\d[\d,\.]*)\s*(?:لحد|لغاية|ل|الى|إلى)\s*(\d[\d,\.]*)', 'range'),
    # "ب 5000" / "بسعر 5000"
    (r'(?:ب|بسعر|بـ)\s*(\d[\d,\.]*)', 'exact'),
    # Standalone numbers >= 100 likely prices
    (r'\b(\d{3,})\b', 'approx'),
]


def extract_entities(query: str) -> dict:
    """
    Extract structured entities from an Egyptian Arabic query.
    Zero LLM — pure regex + keyword matching.

    Returns:
    {
        "product": str,        # cleaned product search term
        "price_min": float|None,
        "price_max": float|None,
        "location": str|None,
        "category": str|None,
    }
    """
    q = query.strip()
    product_terms = q  # Will remove extracted parts
    price_min = None
    price_max = None
    location = None
    category = None

    # ── Extract Location ──
    for loc in sorted(_LOCATIONS, key=len, reverse=True):  # longest match first
        patterns = [
            f'في {loc}', f'ف{loc}', f'فى {loc}', f'من {loc}', f'ب{loc}',
            loc,  # standalone
        ]
        for pat in patterns:
            if pat in q:
                location = loc
                product_terms = product_terms.replace(pat, '').strip()
                break
        if location:
            break

    # ── Extract Price ──
    for pattern, ptype in _PRICE_PATTERNS:
        match = re.search(pattern, q)
        if match:
            if ptype == 'max':
                price_max = float(match.group(1).replace(',', ''))
                product_terms = product_terms[:match.start()] + product_terms[match.end():]
            elif ptype == 'min':
                price_min = float(match.group(1).replace(',', ''))
                product_terms = product_terms[:match.start()] + product_terms[match.end():]
            elif ptype == 'range':
                price_min = float(match.group(1).replace(',', ''))
                price_max = float(match.group(2).replace(',', ''))
                product_terms = product_terms[:match.start()] + product_terms[match.end():]
            elif ptype == 'exact':
                val = float(match.group(1).replace(',', ''))
                price_min = val * 0.7  # ±30% range
                price_max = val * 1.3
                product_terms = product_terms[:match.start()] + product_terms[match.end():]
            break  # Take first match only

    # ── Extract Category ──
    q_lower = normalize_arabic(q)
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in q or normalize_arabic(kw) in q_lower:
                category = cat
                break
        if category:
            break

    # ── Clean product terms ──
    # Remove filler words
    fillers = ['عايز', 'عاوز', 'محتاج', 'عندك', 'عندكم', 'فيه', 'في',
               'بتاع', 'ابغى', 'دور', 'دورلي', 'هات', 'هاتلي', 'جيبلي',
               'لو سمحت', 'من فضلك', 'يا', 'بقى', 'كدا', 'كده']
    for f in fillers:
        product_terms = product_terms.replace(f, '')
    product_terms = ' '.join(product_terms.split()).strip('؟?!. ')

    entities = {
        "product": product_terms or q,
        "price_min": price_min,
        "price_max": price_max,
        "location": location,
        "category": category,
    }

    logger.info(f"[IntentRouter] Entities: {entities}")
    return entities
