"""
HF Space-based image classifier for product categorization.
Calls the Omarh353111/khorda_yolo HuggingFace Space remotely
instead of loading YOLO/ultralytics locally, avoiding ~300 MB
RAM overhead on Render.
"""

import os
import json
import logging
import requests as http_requests

logger = logging.getLogger(__name__)

# ─── HF Space configuration ─────────────────────────────────
HF_SPACE_URL = os.getenv(
    "HF_SPACE_URL", "https://omarh353111-khorda-yolo.hf.space"
)
HF_API_TOKEN = os.getenv("HF_API_TOKEN", "")



# Map detected YOLO class names (canonicalized) → Arabic category labels
CATEGORY_MAP = {
    # ─── أثاث وديكور (Furniture & Decor) ───
    'bed': 'أثاث وديكور',
    'chair': 'أثاث وديكور',
    'cabinet': 'أثاث وديكور',
    'cupboard': 'أثاث وديكور',
    'curtain': 'أثاث وديكور',
    'lamp': 'أثاث وديكور',
    'mirror': 'أثاث وديكور',
    'sofa': 'أثاث وديكور',
    'table': 'أثاث وديكور',
    'wardrobe': 'أثاث وديكور',
    'dressing_table': 'أثاث وديكور',
    'food_trip': 'أثاث وديكور',
    'safe': 'أثاث وديكور',
    'office': 'أثاث وديكور',

    # ─── الكترونيات واجهزه (Electronics & Devices) ───
    'laptop': 'الكترونيات واجهزه',
    'computer': 'الكترونيات واجهزه',
    'mobile_phone': 'الكترونيات واجهزه',
    'tv': 'الكترونيات واجهزه',
    'camera': 'الكترونيات واجهزه',
    'headphone': 'الكترونيات واجهزه',
    'airpods': 'الكترونيات واجهزه',
    'speaker': 'الكترونيات واجهزه',
    'receiver': 'الكترونيات واجهزه',
    'router': 'الكترونيات واجهزه',
    'printer': 'الكترونيات واجهزه',
    'keyboard': 'الكترونيات واجهزه',
    'watch': 'الكترونيات واجهزه',
    'controller': 'الكترونيات واجهزه',
    'ps_console': 'الكترونيات واجهزه',
    'pc_case': 'الكترونيات واجهزه',

    # ─── أجهزة منزلية (Home Appliances) ───
    'washing_machine': 'أجهزة منزلية',
    'fridge': 'أجهزة منزلية',
    'cooker': 'أجهزة منزلية',
    'microwave': 'أجهزة منزلية',
    'blender': 'أجهزة منزلية',
    'ac_unit': 'أجهزة منزلية',
    'fan': 'أجهزة منزلية',
    'heater': 'أجهزة منزلية',
    'water_heater': 'أجهزة منزلية',
    'iron': 'أجهزة منزلية',
    'vacuum_cleaner': 'أجهزة منزلية',
    'water_filter': 'أجهزة منزلية',
    'gas_cylinder': 'أجهزة منزلية',
    'freighter': 'أجهزة منزلية',

    # ─── خورده ومعادن (Scrap & Metals) ───
    'korda': 'خورده ومعادن',
    'scrap_metal': 'خورده ومعادن',
    'copper_wire': 'خورده ومعادن',
    'wire': 'خورده ومعادن',
    'aluminum': 'خورده ومعادن',
    'equipment': 'خورده ومعادن',
    'mator': 'خورده ومعادن',

    # ─── سيارات للبيع (Cars) ───
    'car': 'سيارات للبيع',

    # ─── عقارات (Real Estate) ───
    'building': 'عقارات',

    # ─── كتب (Books) ───
    'book': 'كتب',
}

# Map Arabic category labels → Django model category IDs
ARABIC_TO_CATEGORY_ID = {
    'أثاث وديكور': 'furniture',
    'الكترونيات واجهزه': 'electronics',
    'أجهزة منزلية': 'appliances',
    'خورده ومعادن': 'scrap_metals',
    'سيارات للبيع': 'cars',
    'عقارات': 'real_estate',
    'كتب': 'books',
    'أخرى': 'other',
}

# Human-readable Arabic labels for YOLO classes (for agent target dropdown)
YOLO_CLASS_LABELS = {
    # أثاث
    'bed': 'سرير', 'chair': 'كرسي', 'cabinet': 'خزانة',
    'cupboard': 'دولاب', 'curtain': 'ستارة', 'lamp': 'لمبة / أباجورة',
    'mirror': 'مرآة', 'sofa': 'كنبة', 'table': 'طاولة / ترابيزة',
    'wardrobe': 'دولاب ملابس', 'dressing_table': 'تسريحة', 
    'food_trip': 'سفرة', 'safe': 'خزنة',
    # الكترونيات
    'laptop': 'لابتوب', 'computer': 'كمبيوتر',
    'mobile_phone': 'موبايل', 'tv': 'تلفزيون', 'camera': 'كاميرا',
    'headphone': 'سماعات', 'airpods': 'سماعات إيربودز',
    'speaker': 'سبيكر', 'receiver': 'رسيفر',
    'router': 'راوتر', 'printer': 'طابعة',
    'keyboard': 'كيبورد', 'watch': 'ساعة',
    'controller': 'دراعة تحكم', 'ps_console': 'بلايستيشن',
    'pc_case': 'كيسة كمبيوتر',
    # أجهزة منزلية
    'washing_machine': 'غسالة', 'fridge': 'ثلاجة', 
    'cooker': 'بوتاجاز', 'microwave': 'ميكروويف', 'blender': 'خلاط',
    'ac_unit': 'تكييف', 'fan': 'مروحة',
    'heater': 'دفاية', 'water_heater': 'سخان مياه',
    'iron': 'مكواة', 'vacuum_cleaner': 'مكنسة كهربائية', 
    'water_filter': 'فلتر مياه', 'gas_cylinder': 'أنبوبة غاز', 
    'freighter': 'ديب فريزر',
    # خردة
    'korda': 'خردة', 'scrap_metal': 'خردة معادن',
    'copper_wire': 'سلك نحاس', 'wire': 'سلك',
    'aluminum': 'ألومنيوم', 'equipment': 'معدات', 'mator': 'موتور',
    # سيارات
    'car': 'سيارة',
    # عقارات
    'building': 'مبنى', 'office': 'مكتب / أوفيس',
    # كتب
    'book': 'كتاب',
}

def normalize_class(class_name: str) -> str:
    """Normalize YOLO raw class to a unified canonical key."""
    if not class_name:
        return 'other'
    
    key = class_name.strip().lower().replace(' ', '_')
    
    # Merge duplicates and synonyms
    unified = {
        'refrigerator': 'fridge',
        'stove': 'cooker',
        'gas_bottle': 'gas_cylinder',
        'phone': 'mobile_phone',
    }
    
    return unified.get(key, key)


def get_available_targets():
    """
    Return a list of all YOLO classes the agent can target,
    grouped by their Arabic category, for the frontend dropdown.
    """
    targets = []
    for class_name, arabic_category in CATEGORY_MAP.items():
        label = YOLO_CLASS_LABELS.get(class_name, class_name)
        targets.append({
            'id': class_name,
            'label': f"{label} ({arabic_category})",
            'label_ar': label,
            'category': arabic_category,
        })
    return targets


def guess_item_from_text(text: str) -> str:
    """
    Fallback: If YOLO fails or HF space is down, try to guess the class from the product title.
    Matches Arabic words in the title to the YOLO classes.
    """
    if not text:
        return None

    text_lower = text.lower()

    # ── Extra keyword map for common Arabic/slang words users actually type ──
    EXTRA_KEYWORDS = {
        # خردة ومعادن
        'خورده':      'korda',
        'خرده':       'korda',
        'خردة':       'korda',
        'سكراب':      'scrap_metal',
        'scrap':      'scrap_metal',
        'نحاس':       'copper_wire',
        'سلك':        'wire',
        'كابل':       'wire',
        'ألمنيوم':    'aluminum',
        'الومنيوم':   'aluminum',
        'حديد':       'scrap_metal',
        'معادن':      'scrap_metal',
        'موتور':      'mator',
        'مواتير':     'mator',
        'معدة':       'equipment',
        'معدات':      'equipment',
        # إلكترونيات
        'موبايل':     'mobile_phone',
        'تليفون':     'mobile_phone',
        'لاب توب':    'laptop',
        'لابتوب':     'laptop',
        'تلفزيون':    'tv',
        'شاشة':       'tv',
        'كاميرا':     'camera',
        'سماعة':      'headphone',
        'سبيكر':      'speaker',
        'راوتر':      'router',
        'طابعة':      'printer',
        'بلايستيشن':  'ps_console',
        # أجهزة منزلية
        'ثلاجة':      'fridge',
        'غسالة':      'washing_machine',
        'بوتاجاز':    'cooker',
        'ميكروويف':   'microwave',
        'تكييف':      'ac_unit',
        'مكيف':       'ac_unit',
        'سخان':       'water_heater',
        'مكواة':      'iron',
        'مكنسة':      'vacuum_cleaner',
        'فريزر':      'freighter',
        # أثاث
        'كنبة':       'sofa',
        'كنبه':       'sofa',
        'سرير':       'bed',
        'طاولة':      'table',
        'ترابيزة':    'table',
        'كرسي':       'chair',
        'دولاب':      'wardrobe',
        'ستارة':      'curtain',
        # سيارات
        'سيارة':      'car',
        'عربية':      'car',
        # كتب
        'كتاب':       'book',
        'كتب':        'book',
    }

    for keyword, class_key in EXTRA_KEYWORDS.items():
        if keyword in text_lower:
            return class_key

    # Then check exact English keys
    for key in CATEGORY_MAP.keys():
        if key.lower() in text_lower:
            return key

    # Finally check Arabic labels from YOLO_CLASS_LABELS
    for key, ar_label in YOLO_CLASS_LABELS.items():
        # Split by " / " for labels like 'طاولة / ترابيزة'
        labels = [l.strip() for l in ar_label.split('/')]
        for label in labels:
            if label and label in text_lower:
                return key

    return None

def _lookup_category(class_name: str):
    """Case-insensitive category lookup. Returns Arabic label or None."""
    return CATEGORY_MAP.get(class_name)


# ─────────────────────────────────────────────────────────────
# gradio_client-based prediction (more reliable than raw HTTP)
# ─────────────────────────────────────────────────────────────

def _predict_via_gradio_client(image_bytes: bytes, filename: str = "image.jpg") -> str | None:
    """
    Use gradio_client to call the HF Space predict endpoint.
    Writes image to a temp file, calls predict, returns the class string.
    Returns None on failure.
    """
    import tempfile
    from gradio_client import Client, handle_file

    tmp_path = None
    try:
        # Write bytes to a temp file so handle_file() can read it
        suffix = os.path.splitext(filename)[-1] or ".jpg"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        client = Client(
            "Omarh353111/khorda_yolo",
            token=HF_API_TOKEN or None,
            verbose=False,
        )
        result = client.predict(
            image_path=handle_file(tmp_path),
            api_name="/predict",
        )
        # result = (image_filepath, class_string)
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            detected = result[1]
            if isinstance(detected, str):
                return detected.strip() or None
        return None

    except Exception as e:
        logger.warning(f"[AI] gradio_client predict failed: {e}")
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────
# Public API  (same signature as the old local-YOLO version)
# ─────────────────────────────────────────────────────────────

def classify_image(image_path: str) -> dict:
    """
    Classify a product image via the remote HF Space YOLO model.
    Uses gradio_client for reliable communication with the Space.
    Supports both local file paths and remote URLs (Cloudinary, etc.).

    Returns a dict with keys:
        category, category_label, confidence, detected_class
    """

    fallback = {
        'category': 'other',
        'category_label': 'أخرى',
        'confidence': 0.0,
        'detected_class': None,
    }

    try:
        is_url = image_path.startswith("http://") or image_path.startswith("https://")

        # ── Step 1: Get image bytes ──────────────────────────
        if is_url:
            print(f"[AI] [OUT] Downloading image from URL: {image_path[:80]}...")
            dl = http_requests.get(image_path, timeout=15)
            dl.raise_for_status()
            image_bytes = dl.content
            filename = "image.jpg"
        else:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            filename = os.path.basename(image_path)

        # ── Step 2: Run prediction via gradio_client ──────────
        print(f"[AI] [RUN] Running YOLO inference via gradio_client...")
        detected_class = _predict_via_gradio_client(image_bytes, filename)

        if not detected_class or detected_class == "other":
            logger.warning(
                f"[AI] YOLO returned '{detected_class}'. Falling back to text guess."
            )
            return fallback

        # ── Step 3: Normalize & map to category ──────────────
        normalized = normalize_class(detected_class)
        print(
            f"[AI] [SEARCH] YOLO detected: '{detected_class}' "
            f"-> Normalized: '{normalized}'"
        )

        arabic_label = _lookup_category(normalized)
        if not arabic_label:
            logger.warning(
                f"[AI] Unknown class: '{normalized}', trying fuzzy match..."
            )
            for k in CATEGORY_MAP:
                if k in normalized:
                    arabic_label = CATEGORY_MAP[k]
                    normalized = k
                    break
            if not arabic_label:
                return fallback

        category_id = ARABIC_TO_CATEGORY_ID.get(arabic_label, "other")
        print(f"[AI] [OK] Result: '{normalized}' -> category='{category_id}'")

        return {
            'category': category_id,
            'category_label': arabic_label,
            'confidence': 1.0,
            'detected_class': normalized,
        }

    except Exception as e:
        logger.error(f"[AI] classify_image error: {e}")
        import traceback
        traceback.print_exc()
        return fallback
