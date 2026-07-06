"""
Smart SQL Generator — V2 Single-Shot with JOINs.

Replaces the heavy LangChain Agent (~15s) with a single LLM call (~3s).
The LLM receives the DB schema + extracted entities and writes optimal SQL.

Key improvement: SQL includes JOINs to auth_user + user_profiles,
so seller data comes back in ONE query (no separate enrichment step).
"""

import os
import re
import logging
from django.db import connection
from langchain_core.prompts import ChatPromptTemplate
from rag.graph.config import get_llm

logger = logging.getLogger(__name__)

MAX_ROWS = 4

# Tables the LLM is allowed to reference
ALLOWED_TABLES = {'products', 'auctions', 'bids', 'product_images',
                  'auth_user', 'user_profiles'}

# Write operations that must never appear
FORBIDDEN_KEYWORDS = [
    'DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 'TRUNCATE',
    'CREATE', 'REPLACE', 'GRANT', 'REVOKE', 'EXEC', 'EXECUTE',
    'MERGE', 'COMMIT', 'ROLLBACK', 'SAVEPOINT',
]


# ═══════════════════════════════════════════════════════════
# Safety Validator
# ═══════════════════════════════════════════════════════════

def validate_sql(sql: str) -> tuple[bool, str]:
    """Block any non-SELECT or dangerous SQL."""
    if not sql or not sql.strip():
        return False, "Empty SQL"

    sql = sql.strip().rstrip(';').strip()
    sql_upper = sql.upper()

    if not sql_upper.startswith('SELECT'):
        return False, "Only SELECT allowed"

    for kw in FORBIDDEN_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', sql_upper):
            return False, f"Forbidden: {kw}"

    # Check no access to sensitive tables
    referenced = set(
        m.lower() for m in re.findall(
            r'(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)', sql, re.IGNORECASE
        )
    )
    illegal = referenced - ALLOWED_TABLES
    if illegal:
        return False, f"Illegal tables: {illegal}"

    return True, ""


# ═══════════════════════════════════════════════════════════
# Schema (embedded — no need for dynamic discovery)
# ═══════════════════════════════════════════════════════════

SCHEMA = """
TABLE products (
  id BIGINT PK, title VARCHAR(200), description TEXT, price NUMERIC(10,2),
  category VARCHAR(20), condition VARCHAR(10), status VARCHAR(10),
  location VARCHAR(200), is_auction BOOLEAN, owner_id INT FK→auth_user,
  phone_number VARCHAR(20), detected_item VARCHAR(100),
  views_count INT, created_at TIMESTAMP
)

TABLE auth_user (id INT PK, username VARCHAR(150))

TABLE user_profiles (
  user_id INT FK→auth_user, seller_rating DECIMAL(3,2),
  trust_score INT, total_sales INT, is_verified BOOLEAN
)

TABLE auctions (
  id BIGINT PK, product_id BIGINT FK→products,
  starting_bid NUMERIC, current_bid NUMERIC,
  end_time TIMESTAMP, is_active BOOLEAN
)
"""


# ═══════════════════════════════════════════════════════════
# Single-Shot SQL Prompt
# ═══════════════════════════════════════════════════════════

SQL_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a PostgreSQL expert for "Tadwera" (Egyptian marketplace).
Write ONE optimal SELECT query. Output ONLY raw SQL, no markdown.

SCHEMA:
{schema}

RULES:
1. Always JOIN auth_user and user_profiles to get seller data:
   JOIN auth_user u ON p.owner_id = u.id
   LEFT JOIN user_profiles up ON u.id = up.user_id
2. Always include: WHERE p.status = 'active'
3. Use ILIKE with multiple OR patterns for Arabic text variations (at least 3 patterns).
   Example: "دراعات بلاستيشن" → '%بلاستيشن%', '%بلايستيشن%', '%جاك%', '%PS%'
4. Search BOTH p.title AND p.description
5. LIMIT {max_rows}
6. SELECT these columns:
   p.id, p.title, p.description, p.price, p.category, p.condition,
   p.location, p.is_auction, p.phone_number, p.views_count,
   u.username as seller_name,
   COALESCE(up.seller_rating, 0) as seller_rating,
   COALESCE(up.trust_score, 50) as trust_score,
   COALESCE(up.total_sales, 0) as total_sales
7. If price/location constraints are provided, add them as WHERE clauses.
8. Output ONLY the SQL. No explanation. No backticks."""),
    ("user", """Query: {query}
Product: {product}
Price Min: {price_min}
Price Max: {price_max}
Location: {location}
Category: {category}""")
])


def generate_sql(query: str, entities: dict) -> str:
    """Single-shot LLM call to generate SQL with JOINs. Retries on 429."""
    from rag.graph.config import mark_key_exhausted

    max_retries = 3
    for attempt in range(max_retries):
        try:
            llm, current_key = get_llm(temperature=0)
            chain = SQL_PROMPT | llm

            result = chain.invoke({
                "schema": SCHEMA.strip(),
                "max_rows": MAX_ROWS,
                "query": query,
                "product": entities.get("product", query),
                "price_min": entities.get("price_min") or "none",
                "price_max": entities.get("price_max") or "none",
                "location": entities.get("location") or "none",
                "category": entities.get("category") or "none",
            })

            sql = result.content.strip()
            sql = sql.replace("```sql", "").replace("```", "").strip()

            if not sql.upper().startswith("SELECT"):
                logger.warning(f"[SQL] Non-SELECT output: {sql[:80]}")
                return ""

            logger.info(f"[SQL] Generated: {sql[:120]}")
            return sql

        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "rate_limit" in error_str:
                mark_key_exhausted(current_key)
                logger.warning(f"[SQL] 429 on attempt {attempt+1}/{max_retries}, rotating key...")
                continue
            logger.error(f"[SQL] Generation failed: {e}")
            return ""

    logger.error("[SQL] All retries exhausted")
    return ""


def execute_safe_sql(sql: str) -> tuple[list[dict], str]:
    """Validate and execute SQL via Django connection."""
    is_valid, error = validate_sql(sql)
    if not is_valid:
        logger.warning(f"[SQL] Rejected: {error}")
        return [], error

    if 'LIMIT' not in sql.upper():
        sql = sql.rstrip().rstrip(';') + f" LIMIT {MAX_ROWS}"

    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        results = []
        for row in rows:
            item = dict(zip(columns, row))
            for k, v in item.items():
                if hasattr(v, 'as_integer_ratio'):
                    item[k] = float(v)
            item['source'] = 'sql'
            results.append(item)

        logger.info(f"[SQL] Executed → {len(results)} rows")
        return results, ""

    except Exception as e:
        logger.error(f"[SQL] Execution failed: {e}")
        return [], str(e)


def sql_search(query: str, entities: dict = None) -> tuple[list[dict], str]:
    """Full pipeline: generate SQL → validate → execute."""
    if entities is None:
        entities = {"product": query}

    sql = generate_sql(query, entities)
    if not sql:
        return [], ""

    results, error = execute_safe_sql(sql)
    if error:
        return [], sql

    return results, sql
