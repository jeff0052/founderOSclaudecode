"""知识文档层 — 每节点 Markdown 文件存储，支持父节点继承。

Storage layout:
    data/knowledge/{node_id}/
    ├── overview.md
    ├── requirements.md
    ├── architecture.md
    └── {custom_name}.md
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional


def set_knowledge(knowledge_dir: str, node_id: str, doc_type: str, content: str) -> None:
    """Write or overwrite a knowledge doc for node_id."""
    node_dir = os.path.join(knowledge_dir, node_id)
    os.makedirs(node_dir, exist_ok=True)
    filepath = os.path.join(node_dir, f"{doc_type}.md")
    with open(filepath, "w") as f:
        f.write(content)


def get_knowledge(
    knowledge_dir: str,
    node_id: str,
    doc_type: Optional[str] = None,
    store=None,
    inherit: bool = False,
):
    """Read knowledge docs for node_id.

    - doc_type=None: returns dict {doc_type: content} of all docs.
    - doc_type set: returns str content or None if not found.
    - inherit=True + store set: walk parent chain for missing docs.
    """
    if doc_type is not None:
        return _get_single(knowledge_dir, node_id, doc_type, store=store, inherit=inherit)
    else:
        return _get_all(knowledge_dir, node_id, store=store, inherit=inherit)


def _get_single(
    knowledge_dir: str,
    node_id: str,
    doc_type: str,
    store=None,
    inherit: bool = False,
) -> Optional[str]:
    """Return content of a single doc type, or None if not found."""
    filepath = os.path.join(knowledge_dir, node_id, f"{doc_type}.md")
    if os.path.isfile(filepath):
        with open(filepath, "r") as f:
            return f.read()

    # If not found and inheritance requested, walk up the parent chain
    if inherit and store is not None:
        node = store.get_node(node_id)
        if node is not None and node.parent_id is not None:
            return _get_single(knowledge_dir, node.parent_id, doc_type, store=store, inherit=True)

    return None


def _get_all(
    knowledge_dir: str,
    node_id: str,
    store=None,
    inherit: bool = False,
) -> Dict[str, str]:
    """Return dict of all docs for this node, optionally merging with ancestors."""
    result: Dict[str, str] = {}

    if inherit and store is not None:
        # Walk parent chain first (lowest priority), then override with own docs
        node = store.get_node(node_id)
        if node is not None and node.parent_id is not None:
            parent_docs = _get_all(knowledge_dir, node.parent_id, store=store, inherit=True)
            result.update(parent_docs)

    # Own docs override anything inherited
    own_docs = _read_own_docs(knowledge_dir, node_id)
    result.update(own_docs)

    return result


def _read_own_docs(knowledge_dir: str, node_id: str) -> Dict[str, str]:
    """Read all .md files in the node's own directory."""
    node_dir = os.path.join(knowledge_dir, node_id)
    docs: Dict[str, str] = {}
    if not os.path.isdir(node_dir):
        return docs
    for filename in os.listdir(node_dir):
        if filename.endswith(".md"):
            doc_type = filename[:-3]  # strip .md
            filepath = os.path.join(node_dir, filename)
            with open(filepath, "r") as f:
                docs[doc_type] = f.read()
    return docs


def delete_knowledge(knowledge_dir: str, node_id: str, doc_type: str) -> None:
    """Delete a knowledge doc file. No-op if it doesn't exist."""
    filepath = os.path.join(knowledge_dir, node_id, f"{doc_type}.md")
    try:
        os.remove(filepath)
    except FileNotFoundError:
        pass


def list_knowledge(knowledge_dir: str, node_id: str) -> List[str]:
    """List doc types this node owns (not inherited)."""
    node_dir = os.path.join(knowledge_dir, node_id)
    if not os.path.isdir(node_dir):
        return []
    doc_types: List[str] = []
    for filename in os.listdir(node_dir):
        if filename.endswith(".md"):
            doc_types.append(filename[:-3])
    return doc_types
