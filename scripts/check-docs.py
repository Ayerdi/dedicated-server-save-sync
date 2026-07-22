#!/usr/bin/env python3
import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
LINK_RE = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")


def main():
    failures = []
    markdown_files = sorted(
        path for path in ROOT.rglob("*.md") if ".git" not in path.parts
    )
    for document in markdown_files:
        text = document.read_text(encoding="utf-8")
        for raw_target in LINK_RE.findall(text):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            local = unquote(target.split("#", 1)[0])
            if not local:
                continue
            resolved = (document.parent / local).resolve()
            if ROOT not in resolved.parents and resolved != ROOT:
                failures.append(f"{document.relative_to(ROOT)}: sale del repositorio: {target}")
            elif not resolved.exists():
                failures.append(f"{document.relative_to(ROOT)}: enlace inexistente: {target}")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Documentación OK: {len(markdown_files)} archivos Markdown revisados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
