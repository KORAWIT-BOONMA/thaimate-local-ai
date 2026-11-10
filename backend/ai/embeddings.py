
import httpx


# ==========================================
# BGE-M3 Configuration
# ==========================================

OLLAMA_URL = "http://localhost:11434"
EMBEDDING_MODEL = "bge-m3"

EMBED_TIMEOUT = httpx.Timeout(
    180.0,
    connect=10.0,
)


# ==========================================
# Custom Error
# ==========================================

class EmbeddingError(Exception):
    """Error while generating text embeddings."""


# ==========================================
# Embedding Functions
# ==========================================

async def embed_texts(
    texts: list[str],
    keep_alive: str | int = 0,
) -> list[list[float]]:
    """
    Convert multiple texts into embedding vectors.

    keep_alive=0 unloads BGE-M3 after the request.
    """

    if not texts:
        return []

    cleaned_texts = [
        text.strip()
        for text in texts
        if isinstance(text, str) and text.strip()
    ]

    if not cleaned_texts:
        return []

    if len(cleaned_texts) > 16:
        raise EmbeddingError(
            "ส่งข้อความได้สูงสุด 16 รายการต่อครั้ง"
        )

    payload = {
        "model": EMBEDDING_MODEL,
        "input": cleaned_texts,
        "truncate": True,
        "keep_alive": keep_alive,
    }

    try:
        async with httpx.AsyncClient(
            timeout=EMBED_TIMEOUT
        ) as client:

            response = await client.post(
                f"{OLLAMA_URL}/api/embed",
                json=payload,
            )

            response.raise_for_status()

            data = response.json()
            embeddings = data.get("embeddings")

            if not isinstance(embeddings, list):
                raise EmbeddingError(
                    "Ollama ไม่ส่งข้อมูล Embeddings กลับมา"
                )

            if len(embeddings) != len(cleaned_texts):
                raise EmbeddingError(
                    "จำนวน Embeddings ไม่ตรงกับจำนวนข้อความ"
                )

            if any(
                not isinstance(vector, list) or not vector
                for vector in embeddings
            ):
                raise EmbeddingError(
                    "ข้อมูล Vector ไม่ถูกต้อง"
                )

            return embeddings

    except httpx.ConnectError as exc:
        raise EmbeddingError(
            "เชื่อมต่อ Ollama ไม่ได้"
        ) from exc

    except httpx.TimeoutException as exc:
        raise EmbeddingError(
            "BGE-M3 ใช้เวลาประมวลผลเกินกำหนด"
        ) from exc

    except httpx.HTTPStatusError as exc:
        raise EmbeddingError(
            f"Ollama Embedding Error: {exc.response.text}"
        ) from exc

    except httpx.HTTPError as exc:
        raise EmbeddingError(
            f"เกิดข้อผิดพลาดในการเชื่อมต่อ: {exc}"
        ) from exc


async def embed_query(text: str) -> list[float]:
    """Generate an embedding for a search query."""

    results = await embed_texts([text])

    if not results:
        raise EmbeddingError(
            "ไม่สามารถสร้าง Query Embedding ได้"
        )

    return results[0]


async def embed_documents(
    documents: list[str],
    keep_alive: str | int = "30s",
) -> list[list[float]]:
    """Generate embeddings for documents."""

    return await embed_texts(
        documents,
        keep_alive=keep_alive,
    )