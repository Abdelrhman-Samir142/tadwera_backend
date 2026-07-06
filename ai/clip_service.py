import os
import logging
import base64
import requests

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/embeddings"
EMBED_MODEL = "nvidia/llama-nemotron-embed-vl-1b-v2:free"

def get_image_embedding(image_bytes: bytes) -> list[float]:
    """
    Get 2048-dim true visual embedding for an image using OpenRouter.
    Model: nvidia/llama-nemotron-embed-vl-1b-v2:free
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not set in .env")

    img_b64 = base64.b64encode(image_bytes).decode()
    data_url = f"data:image/jpeg;base64,{img_b64}"

    payload = {
        "model": EMBED_MODEL,
        "input": [
            {
                "content": [
                    {"type": "text", "text": "Describe the visual features of this item for similarity search:"},
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]
            }
        ],
        "encodingFormat": "float"
    }

    try:
        response = requests.post(
            OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )

        if response.status_code != 200:
            logger.error(f"[VisionService] OpenRouter error: {response.text}")
            raise Exception(f"OpenRouter API error: {response.text}")

        result = response.json()
        embedding = result["data"][0]["embedding"]
        return embedding

    except Exception as e:
        logger.error(f"[VisionService] Failed to generate visual embedding: {e}")
        raise Exception("فشل استخراج بيانات الصورة. يرجى المحاولة مرة أخرى.")

def get_text_embedding(text: str) -> list[float]:
    """
    Get 2048-dim text embedding for a text query using the same Nemotron model.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not set in .env")

    payload = {
        "model": EMBED_MODEL,
        "input": [
            {
                "content": [
                    {"type": "text", "text": f"Search query for visual items: {text}"}
                ]
            }
        ],
        "encodingFormat": "float"
    }

    try:
        response = requests.post(
            OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )

        if response.status_code != 200:
            raise Exception(f"OpenRouter API error: {response.text}")

        result = response.json()
        return result["data"][0]["embedding"]

    except Exception as e:
        logger.error(f"[VisionService] Failed to generate text embedding: {e}")
        raise
