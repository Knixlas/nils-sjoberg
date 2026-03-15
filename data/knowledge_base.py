"""
Kunskapsbas – artiklar, principer och träningsteori som Nils
använder i sin coachning. Lagras som .md-filer i knowledge/-mappen.
"""

import re
from datetime import date
from pathlib import Path
from typing import Optional

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parsar YAML-liknande frontmatter från .md-fil."""
    meta = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    val = val.strip().strip("[]")
                    meta[key.strip()] = val
            body = parts[2].strip()
    return meta, body


def _next_id() -> int:
    existing = list(KNOWLEDGE_DIR.glob("*.md"))
    if not existing:
        return 1
    nums = []
    for f in existing:
        match = re.match(r"(\d+)", f.stem)
        if match:
            nums.append(int(match.group(1)))
    return max(nums, default=0) + 1


def list_articles() -> list[dict]:
    KNOWLEDGE_DIR.mkdir(exist_ok=True)
    articles = []
    for f in sorted(KNOWLEDGE_DIR.glob("*.md")):
        meta, body = _parse_frontmatter(f.read_text(encoding="utf-8"))
        articles.append({
            "id": f.stem,
            "file": f.name,
            "title": meta.get("title", f.stem),
            "source": meta.get("source", ""),
            "tags": meta.get("tags", ""),
            "added": meta.get("added", ""),
            "summary": body[:200] + "..." if len(body) > 200 else body,
            "full_text": body,
        })
    return articles


def add_article(title: str, content: str, source: str = "", tags: str = "") -> str:
    KNOWLEDGE_DIR.mkdir(exist_ok=True)
    num = _next_id()
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower().strip())[:40].strip("_")
    filename = f"{num:03d}_{slug}.md"
    filepath = KNOWLEDGE_DIR / filename

    frontmatter = (
        f"---\n"
        f"title: {title}\n"
        f"source: {source}\n"
        f"tags: [{tags}]\n"
        f"added: {date.today().isoformat()}\n"
        f"---\n\n"
    )
    filepath.write_text(frontmatter + content, encoding="utf-8")
    return filepath.stem


def remove_article(article_id: str) -> bool:
    for f in KNOWLEDGE_DIR.glob("*.md"):
        if f.stem == article_id:
            f.unlink()
            return True
    return False


def knowledge_summary() -> str:
    articles = list_articles()
    if not articles:
        return "Ingen kunskapsbas tillganglig."

    lines = [f"Kunskapsbas ({len(articles)} artiklar):"]
    for a in articles:
        lines.append(f"\n  [{a['id']}] {a['title']}")
        if a["source"]:
            lines.append(f"    Kalla: {a['source']}")
        if a["tags"]:
            lines.append(f"    Tags: {a['tags']}")
        lines.append(f"    {a['full_text']}")
    return "\n".join(lines)


def get_full_knowledge() -> str:
    articles = list_articles()
    parts = []
    for a in articles:
        parts.append(f"## {a['title']}\n\n{a['full_text']}")
    return "\n\n---\n\n".join(parts)


if __name__ == "__main__":
    print(knowledge_summary())
