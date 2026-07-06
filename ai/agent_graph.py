import os
from typing import TypedDict
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END

# Define Schema for LLM output
class EvaluationResult(BaseModel):
    is_match: bool = Field(description="True if the product matches the agent's requirements, False otherwise.")
    confidence: str = Field(description="Confidence level: high, medium, or low")
    reason: str = Field(description="Detailed explanation in Egyptian Arabic for why it matched or not")
    decision_type: str = Field(
        description="Category of decision: matched, price_too_high, wrong_brand, wrong_type, wrong_condition, missing_info, wrong_location, partial_match",
        default="matched"
    )

# Define Graph State
class AgentState(TypedDict):
    product_title: str
    product_desc: str
    product_condition: str
    product_price: str
    agent_requirements: str
    agent_max_budget: str
    is_match: bool
    confidence: str
    reason: str
    decision_type: str

def evaluate_node(state: AgentState):
    # Groq model initialization (using llama-3.3-70b-versatile - fast and free)
    api_key = os.environ.get("GROQ_AGENT_API_KEY", "").strip('"').strip("'")
    
    llm = ChatGroq(
        api_key=api_key, 
        model="llama-3.3-70b-versatile",
        temperature=0.1
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """أنت وكيل ذكي لمنصة "تدويرة" — سوق مصري لبيع وشراء المستعمل والخردة.

## مهمتك
قارن بين **المنتج المعروض** و**طلب المشتري** وقرر: هل المنتج ده يناسب اللي بيدور عليه ولا لأ؟

## بيانات مهمة
- ميزانية المشتري القصوى: {budget} جنيه مصري
- لو سعر المنتج أعلى من الميزانية = ❌ لا يطابق (حتى لو كل حاجة تانية مطابقة)

## قواعد المطابقة (بالترتيب)

### 1. نوع المنتج (أهم حاجة)
المنتج لازم يكون **نفس النوع** اللي المشتري طالبه.
- "غسالة" ≠ "ثلاجة" ≠ "بوتاجاز"
- "لابتوب" ≠ "موبايل" ≠ "تابلت"
- "سرير" ≠ "كنبة" ≠ "دولاب"
- لو النوع مختلف → decision_type = "wrong_type"

### 2. الماركة / الموديل
لو المشتري حدد ماركة معينة (توشيبا، سامسونج، LG، HP، إلخ):
- الماركة لازم تكون موجودة في العنوان أو الوصف
- منتج بدون ماركة أو بماركة مختلفة = ❌
- لو الماركة غلط → decision_type = "wrong_brand"

### 3. السعر والميزانية
- سعر المنتج لازم يكون ≤ ميزانية المشتري ({budget} جنيه)
- لو السعر أعلى → decision_type = "price_too_high"
- لو السعر مش معروف → اعتبره مش مطابق

### 4. الحالة
- لو المشتري قال "جديد" أو "مستعمل" أو "حالة ممتازة" → لازم يتوافق
- لو الحالة متناقضة → decision_type = "wrong_condition"

### 5. الموقع
- لو المشتري حدد مدينة (القاهرة، الإسكندرية، إلخ) → لازم يتوافق
- لو المكان مختلف → decision_type = "wrong_location"

### 6. مواصفات تانية
- لو المشتري ذكر حجم، لون، سعة، موديل معين → لازم يتوافق
- لو مفيش معلومات كافية → decision_type = "missing_info"

### 7. قاعدة الشك
- لو المعلومات ناقصة أو مش واضحة أو متناقضة → is_match = false

## أمثلة

| طلب المشتري | المنتج | النتيجة | السبب |
|---|---|---|---|
| "غسالة توشيبا أقل من 5000" (ميزانية 5000) | غسالة توشيبا 8 كيلو - 4500 جنيه | ✅ مطابق | الماركة توشيبا والسعر 4500 أقل من الميزانية 5000 ✅ |
| "غسالة توشيبا" (ميزانية 3000) | غسالة توشيبا فوق أوتوماتيك - 6000 جنيه | ❌ مش مطابق | السعر 6000 جنيه أعلى من الميزانية 3000 جنيه |
| "لابتوب ألعاب" (ميزانية 15000) | لابتوب HP مكتبي - 8000 جنيه | ❌ مش مطابق | اللابتوب مكتبي مش للألعاب |
| "ثلاجة حالة كويسة" (ميزانية 8000) | ثلاجة توشيبا 14 قدم حالة ممتازة - 5000 جنيه | ✅ مطابق | ثلاجة بحالة ممتازة والسعر 5000 في حدود الميزانية 8000 ✅ |
| "كنبة في القاهرة" (ميزانية 4000) | كنبة مودرن في الإسكندرية - 3000 جنيه | ❌ مش مطابق | المنتج في الإسكندرية مش القاهرة |

## شكل الرد
رد بـ JSON فقط:
{{
  "is_match": true أو false,
  "confidence": "high" أو "medium" أو "low",
  "decision_type": "matched" أو "price_too_high" أو "wrong_brand" أو "wrong_type" أو "wrong_condition" أو "wrong_location" أو "missing_info" أو "partial_match",
  "reason": "اكتب سبب مفصل بالعربي المصري يوضح للمستخدم ليه المنتج طابق أو ما طابقش. لو مطابق اذكر السعر والميزانية. لو مش مطابق وضح السبب بالظبط."
}}

## تنبيه مهم
- السبب (reason) هيتبعت للمستخدم كإشعار، فلازم يكون واضح ومفهوم لأي حد عادي
- اكتب بالعربي المصري (مش فصحى)
- لو المنتج مطابق اذكر: اسم المنتج + السعر + إنه في حدود الميزانية
- لو مش مطابق اذكر: السبب الرئيسي بالظبط (السعر عالي / الماركة غلط / النوع مختلف / إلخ)
"""),
        ("user", """المنتج المعروض:
- العنوان: {title}
- الوصف: {desc}
- الحالة: {condition}
- السعر: {price} جنيه

ميزانية المشتري القصوى: {budget} جنيه

طلب المشتري:
{req}

هل المنتج ده يناسب طلب المشتري؟ رد بـ JSON فقط.""")
    ])
    
    # Using LangChain structured output for Groq
    structured_llm = llm.with_structured_output(EvaluationResult)
    chain = prompt | structured_llm
    
    try:
        result = chain.invoke({
            "title": state.get("product_title", ""),
            "desc": state.get("product_desc", ""),
            "condition": state.get("product_condition", ""),
            "price": str(state.get("product_price", "0")),
            "budget": str(state.get("agent_max_budget", "0")),
            "req": state.get("agent_requirements", "")
        })
        return {
            "is_match": result.is_match, 
            "confidence": result.confidence,
            "reason": result.reason,
            "decision_type": result.decision_type
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[AgentGraph] Groq Evaluation Failed: {e}")
        # Default to False for safety
        return {
            "is_match": False, 
            "confidence": "low",
            "reason": f"حصل مشكلة فنية أثناء تقييم المنتج: {str(e)}",
            "decision_type": "missing_info"
        }

# Build LangGraph
graph_builder = StateGraph(AgentState)
graph_builder.add_node("evaluate", evaluate_node)
graph_builder.set_entry_point("evaluate")
graph_builder.add_edge("evaluate", END)

# Compiled Graph instance ready to use
smart_agent_evaluator = graph_builder.compile()
