"""
Synthesis Node — V2 with Inline Guardrails.

Combines:
1. LLM synthesis (Egyptian Arabic, structured output)
2. Guardrail checks (no separate LLM call)
3. Self-correction loop (max 1 retry)
4. Product card builder for frontend

This replaces 3 old nodes: synthesis + quality_guard + data_enrichment.
"""

import logging
from langchain_core.prompts import ChatPromptTemplate
from rag.graph.state import AgentState, SynthesisOutput
from rag.graph.config import get_llm

logger = logging.getLogger(__name__)


SYNTHESIS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """أنت مساعد ذكي لمنصة "تدويرة"، السوق المصري لبيع وشراء المستعمل والخردة.

مهمتك:
تاخذ نتايج البحث، تفلترها، وترجع ردًا بالعامية المصرية الودودة، مع تحديد IDs المنتجات المطابقة في حقل items.

---

## الخطوة 1 — فلتر التطابق
قبل ما تكتب أي حاجة، فكّر كويس:
أ) كاتيجوري المنتج المطلوب إيه؟
ب) لكل نتيجة: هل هي نفس الكاتيجوري أو بديل مقبول؟

قواعد التطابق:
- نفس المنتج أو اسم تاني ليه → مطابق ✓ (مثال: "دراعات بلاستيشن" = "جاك" = "controller")
- بديل من نفس الفئة → مطابق ✓ (مثال: iPhone 14 لو المستخدم طلب iPhone 13)
- كاتيجوري مختلفة خالص → مستبعد ✗ (مثال: تلاجة لو المستخدم طلب غسالة)
- نتيجة معلوماتها ناقصة جدًا (مفيش سعر ولا صورة ولا وصف) → مستبعد ✗

---

## الخطوة 2 — صياغة الرد
### سيناريوهات الرد:

**A — لقيت نتايج مطابقة:**
- ابدأ بـ "لقيتلك..." أو "عندنا..."
- اذكر لكل منتج: السعر + الحالة + المنطقة.
- لو تقييم البائع >= 4 أو trust_score عالي (مثلاً أكبر من 70%): أضف "بائع موثوق ⭐".
- لو فيه مزاد: أضف "عليه مزاد حالياً 🔥" واذكر المزايدة الحالية واقترح عليه يفعل "الوكيل الذكي" (الـ auto-bid agent) عشان يزايد مكانه تلقائياً.
- لو السعر أعلى أو أقل من ميزانية المستخدم، برر ده بلطف (مثلاً: حالته جديدة تماماً أو بائع موثوق).
- اهتم بمطابقة الموقع الجغرافي لو المستخدم حدد مكان معين في طلبه.
- الرسالة 3–5 جمل، مختصرة ومفيدة جداً.
- حط IDs المنتجات المطابقة في items (أرقام صحيحة).

**B — سؤال عام مالوش علاقة بمنتجات:**
- جاوب بشكل طبيعي وودود.
- فكّره بذوق إن تخصصك البيع والشراء في تدويرة.
- items = []

**C — مفيش نتايج مطابقة:**
- قوله بصراحة بس بأسلوب إيجابي.
- اقترح يجرب كلمات تانية أو يرجع بدري.
- items = []

---

## الخطوة 3 — قواعد العامية المصرية
✅ استخدم دائماً كلمات مثل:
لقيتلك / عندنا / شايف / كده / إيه / بتاع / حاجة / أوي / يعني / تمام / طب / ماشي

❌ إياك واستخدام كلمات مثل:
وجدت لك / لديك / يمكنك / المنتج المطلوب / نتائج البحث / استعلامك

---

## أمثلة للتوضيح:

**مثال 1 — نتايج موجودة:**
طلب: "بلاستيشن 5"
نتايج: [#42: PS5 جديدة | 45000 EGP | جديد | المعادي | Seller: أحمد (Rating: 4.5/5, Trust: 90%)]
الرد:
summary: "لقيتلك PS5 بحالة ممتازة بـ 45,000 جنيه في المعادي — بائع موثوق ⭐ وسعره كويس أوي للحالة دي!"
items: [42]

**مثال 2 — سؤال عام:**
طلب: "إيه الفرق بين PS4 وPS5؟"
الرد:
summary: "PS5 أسرع بكتير وبيدعم العاب الجيل الجديد بدقة 4K، بس PS4 لسه عنده مكتبة ألعاب ضخمة وسعره أرخص. لو عاوز تشتري أي منهم، دور عليه في تدويرة وهتلاقي صفقات كويسة! 😊"
items: []

**مثال 3 — نتايج جزئية (فيه مطابق وفيه لأ):**
طلب: "غسالة"
نتايج: [#10: غسالة توشيبا | 8000 EGP | مستعمل | شبرا], [#11: تلاجة سامسونج | 12000 EGP]
الرد:
summary: "لقيتلك غسالة توشيبا مستعملة بـ 8,000 جنيه في شبرا — السعر معقول لو حالتها كويسة، اتواصل مع البائع واتأكد."
items: [10]"""),
    ("user", "طلب المستخدم: {query}\n\nالنتائج المتاحة:\n{context}")
])


def synthesis_node(state: AgentState) -> dict:
    """Synthesize answer + inline guardrails + build product cards."""
    retry = state.get("retry_count", 0)
    fused = state.get("fused_results", [])
    query = state["query"]

    logger.info(f"[Node/Synthesis] {len(fused)} fused results, retry={retry}")

    # ── Build context from fused results ──
    context_lines = []
    valid_ids = set()

    # Pre-fetch details from DB to ensure they are 100% accurate and have current_bid / trust_score
    from marketplace.models import Product, Auction
    pids = []
    for item in fused:
        pid = item.get('id') or item.get('product_id')
        if pid is not None:
            pids.append(int(pid))

    products_db = {p.id: p for p in Product.objects.filter(id__in=pids).select_related('owner', 'owner__profile')}
    auctions_db = {a.product_id: a for a in Auction.objects.filter(product_id__in=pids, is_active=True)}

    for item in fused:
        pid = item.get('id') or item.get('product_id')
        if pid is None:
            continue
        pid = int(pid)
        valid_ids.add(pid)

        db_prod = products_db.get(pid)
        if db_prod:
            item['title'] = db_prod.title
            item['price'] = float(db_prod.price)
            item['condition'] = db_prod.condition
            item['location'] = db_prod.location
            item['is_auction'] = db_prod.is_auction
            item['seller_name'] = db_prod.owner.username
            if hasattr(db_prod.owner, 'profile') and db_prod.owner.profile:
                item['seller_rating'] = float(db_prod.owner.profile.seller_rating)
                item['trust_score'] = int(db_prod.owner.profile.trust_score)
            else:
                item['seller_rating'] = 0.0
                item['trust_score'] = 50

            if db_prod.is_auction:
                db_auc = auctions_db.get(pid)
                if db_auc:
                    item['current_bid'] = float(db_auc.current_bid)

        title = item.get('title', '')
        price = item.get('price', '?')
        condition = item.get('condition', '')
        location = item.get('location', '')
        is_auction = item.get('is_auction', False)
        seller_name = item.get('seller_name', '')
        seller_rating = item.get('seller_rating', 0)
        trust_score = item.get('trust_score', 0)
        current_bid = item.get('current_bid')

        line = f"- #{pid}: {title} | {price} EGP | {condition} | {location}"
        if seller_name:
            line += f" | Seller: {seller_name} (Rating: {seller_rating}/5, Trust: {trust_score}%)"
        if is_auction:
            if current_bid is not None:
                line += f" | AUCTION (Current Bid: {current_bid} EGP)"
            else:
                line += " | AUCTION"
        context_lines.append(line)

    context = "\n".join(context_lines) if context_lines else "(لا توجد نتائج)"

    # ── LLM Synthesis (with key rotation on 429) ──
    from rag.graph.config import mark_key_exhausted

    synthesis = None
    last_error = None
    for attempt in range(3):
        try:
            llm, current_key = get_llm(temperature=0.3)
            structured_llm = llm.with_structured_output(SynthesisOutput)
            chain = SYNTHESIS_PROMPT | structured_llm

            result = chain.invoke({"query": query, "context": context})
            synthesis = result.model_dump()
            break  # Success
        except Exception as e:
            last_error = e
            error_str = str(e)
            if "429" in error_str or "rate_limit" in error_str:
                mark_key_exhausted(current_key)
                logger.warning(f"[Node/Synthesis] 429 on attempt {attempt+1}/3, rotating key...")
                continue
            break

    if synthesis is None:
        logger.error(f"[Node/Synthesis] LLM failed after loop. Last error: {last_error}")
        synthesis = {
            "summary": "حصلت مشكلة تقنية. جرب تاني بعد شوية 🔧",
            "items": [],
            "suggested_action": "set_agent",
        }

    # ── Apply Guardrails ──
    retry_update = _apply_guardrails(synthesis, valid_ids, retry)
    if retry_update:
        return retry_update

    # ── Set suggested action ──
    items = synthesis["items"]
    if not items:
        synthesis["suggested_action"] = "set_agent"
    elif len(items) == 1:
        synthesis["suggested_action"] = "view_listing"
    elif any(
        item.get("is_auction") for item in fused
        if int(item.get("id") or item.get("product_id") or 0) in items
    ):
        synthesis["suggested_action"] = "place_bid"
    elif len(items) >= 3:
        synthesis["suggested_action"] = "compare_prices"
    else:
        synthesis["suggested_action"] = "view_listing"

    # Ensure brand name is always 'تدويرة'
    summary = synthesis.get("summary", "")
    if summary:
        import re
        for old in ["4sale", "4 sale", "four-sale", "four sale", "4-sale", "فور سيل", "فور سيلز", "فور سأل"]:
            summary = re.sub(re.escape(old), "تدويرة", summary, flags=re.IGNORECASE)
        synthesis["summary"] = summary

    # ── Build products_data for frontend (From Fused Results, No DB Query) ──
    products_data = _build_products_data(items, fused)

    logger.info(f"[Node/Synthesis] Done: {len(items)} items, action={synthesis['suggested_action']}")

    return {
        "final_response": synthesis,
        "products_data": products_data,
        "next_step": "end",
    }


def _apply_guardrails(synthesis: dict, valid_ids: set, retry: int) -> dict:
    """Apply guardrails to synthesis output and return retry update if needed."""
    returned_ids = synthesis.get("items", [])
    
    # Type mismatch normalize
    valid_ids_normalized = {int(vid) for vid in valid_ids}
    returned_ids_normalized = []
    for pid in returned_ids:
        try:
            returned_ids_normalized.append(int(pid))
        except (ValueError, TypeError):
            continue

    # Guardrail 1: Remove hallucinated IDs
    filtered_ids = [pid for pid in returned_ids_normalized if pid in valid_ids_normalized]
    
    if len(filtered_ids) < len(returned_ids):
        hallucinated = set(returned_ids_normalized) - set(filtered_ids)
        logger.warning(f"[Guardrail] Removed hallucinated IDs: {hallucinated}")
        synthesis["items"] = filtered_ids

    # Guardrail 2: If retry needed and we haven't retried yet
    if not filtered_ids and valid_ids and retry < 1:
        logger.info("[Guardrail] No items matched but results exist → retry")
        return {
            "retry_count": retry + 1,
            "next_step": "retry",
            "final_response": None,  # Explicitly clear old response
        }
        
    return None


def _build_products_data(item_ids: list, fused: list) -> list:
    """Build frontend-ready product cards from fused results instead of DB."""
    ids = {int(pid) for pid in item_ids[:4] if pid}
    if not ids:
        return []

    products_data = []
    for item in fused:
        pid = item.get('id') or item.get('product_id')
        if pid is None:
            continue
        pid = int(pid)
        if pid in ids:
            products_data.append({
                'id': pid,
                'title': item.get('title', ''),
                'price': str(item.get('current_bid') if item.get('is_auction') and item.get('current_bid') is not None else item.get('price', '?')),
                'condition': item.get('condition', ''),
                'location': item.get('location', ''),
                'is_auction': item.get('is_auction', False),
                'primary_image': item.get('image_url') or item.get('primary_image'),
                'owner_name': item.get('seller_name', 'بائع'),
            })
            ids.remove(pid)  # Avoid duplicates
            
    return products_data
