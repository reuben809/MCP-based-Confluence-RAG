from __future__ import annotations

from typing import Dict, Iterator

from langchain_text_splitters import RecursiveCharacterTextSplitter


def hierarchical_chunks(
    text: str,
    parent_chunk_size: int = 1400,
    child_chunk_size: int = 400,
    parent_overlap: int = 200,
    child_overlap: int = 80,
) -> Iterator[Dict[str, str | int]]:
    """Yield parent/child chunks that preserve semantic boundaries.

    Parent chunks retain larger spans for context while children are optimized for retrieval.
    """

    parent_splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ". ", " "],
        chunk_size=parent_chunk_size,
        chunk_overlap=parent_overlap,
    )
    child_splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ". ", " "],
        chunk_size=child_chunk_size,
        chunk_overlap=child_overlap,
    )

    parents = parent_splitter.split_text(text or "")
    for parent_idx, parent_text in enumerate(parents):
        children = child_splitter.split_text(parent_text)
        for child_idx, child_text in enumerate(children):
            yield {
                "parent_index": parent_idx,
                "child_index": child_idx,
                "parent_text": parent_text.strip(),
                "child_text": child_text.strip(),
            }
