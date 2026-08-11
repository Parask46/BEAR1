import os
from typing import List, Dict, Any
import datetime

# Paths relative to repo root
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(THIS_DIR))  # go up from TOOLS/
MEMORY_LONG_DIR = os.path.join(ROOT_DIR, "MEMORY", "MEMORY-LONG")


def _ensure_memory_dir() -> None:
    os.makedirs(MEMORY_LONG_DIR, exist_ok=True)


def write_note(title: str, content: str, tags: List[str] | None = None) -> Dict[str, Any]:
    """
    Create a new markdown note in MEMORY/MEMORY-LONG with YAML frontmatter,
    at least one wikilink, and optional tags.
    """
    _ensure_memory_dir()
    ts = datetime.datetime.now()
    slug = ts.strftime("%Y-%m-%d_%H-%M-%S")
    fname = f"{slug}-{title.replace(' ', '-')}.md"
    path = os.path.join(MEMORY_LONG_DIR, fname)

    tags = tags or []
    # Always ensure at least one link to an existing node (Bear)
    wikilinks = "[[Bear]] [[MEMORY-LONG]]"

    yaml_tags = tags + ["memory", "ai-generated"]
    yaml_tags_str = ", ".join(yaml_tags)

    body = f"""---
title: {title}
tags: [{yaml_tags_str}]
created: {ts.isoformat()}
---

> [!info] AI-generated memory note
> ==Title==: {title}

{wikilinks}
#memory #bear

{content}
"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(body)

    return {
        "ok": True,
        "filename": fname,
        "path": path,
    }


def read_note(filename: str) -> Dict[str, Any]:
    """
    Read the raw markdown content of a note inside MEMORY/MEMORY-LONG.
    """
    _ensure_memory_dir()
    path = os.path.join(MEMORY_LONG_DIR, filename)

    if not os.path.exists(path):
        return {
            "ok": False,
            "error": f"Note '{filename}' not found in MEMORY-LONG.",
        }

    with open(path, "r", encoding="utf-8") as f:
        data = f.read()

    return {
        "ok": True,
        "filename": filename,
        "content": data,
    }