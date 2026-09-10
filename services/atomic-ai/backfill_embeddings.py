"""Vectoriza entradas de la knowledge_base que aún no tienen embedding.

Uso (con el servidor de embeddings arriba, p. ej. llama_embedding.bat en :8081):
    python backfill_embeddings.py
"""
import asyncio

from app.config import settings
from app.db import init_db
from app.knowledge import backfill_vectors


async def main() -> None:
    await init_db()
    print(f"Embedder: {settings.embeddings_base_url or '(NO configurado)'}")
    print("Buscando entradas sin vector...")
    stats = await backfill_vectors()
    print(f"Listo -> embedded={stats['embedded']}, failed={stats['failed']}, "
          f"total_missing={stats['total_missing']}")


if __name__ == "__main__":
    asyncio.run(main())