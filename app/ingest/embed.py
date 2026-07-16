"""Local multilingual embeddings via sentence-transformers.

The model is loaded lazily so importing this module stays cheap (tests that only
use ``to_vector_literal`` don't pull in torch).
"""
import asyncio

_model = None
_model_name: str | None = None


def get_model(name: str):
    """Load (and cache) the SentenceTransformer model. Blocking — call in a thread."""
    global _model, _model_name
    from sentence_transformers import SentenceTransformer  # lazy import

    if _model is None or _model_name != name:
        _model = SentenceTransformer(name)
        _model_name = name
    return _model


async def embed_text(text: str, name: str) -> list[float]:
    model = get_model(name)
    vec = await asyncio.to_thread(
        lambda: model.encode(text, normalize_embeddings=True)
    )
    return vec.tolist()


def to_vector_literal(vec: list[float]) -> str:
    """Format a vector as a pgvector text literal, e.g. ``[0.5,-1.0]``."""
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"
