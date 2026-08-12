#!/usr/bin/env python3
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "site"
WIKI_ROOT = ROOT / "wiki"
PAGES_PREFIX = "/dedicated-server-save-sync/"
LINK_RE = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
CURRENT_STABLE = "v2.2.2"
PREVIOUS_STABLE = "v2.2.1"

# Files that present the currently recommended release. Historical release
# notes are intentionally excluded because they must keep old version numbers.
CURRENT_SURFACES = (
    "README.md",
    "README.en.md",
    "client/README.md",
    "CONTRIBUTING.md",
    "docs/AGENT-HANDOFF.md",
    "docs/ADAPTING-OTHER-GAMES.md",
    "site/index.html",
    "wiki/Home.md",
    "wiki/Inicio.md",
    "wiki/Instalacion.md",
    "wiki/Installation.md",
    "wiki/Cliente-Windows.md",
    "wiki/Windows-Client.md",
    "wiki/FAQ.md",
    "wiki/FAQ-Espanol.md",
)


class HtmlLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.ids.add(attributes["id"])
        for name in ("href", "src"):
            value = attributes.get(name)
            if value:
                self.targets.append(value)


def resolve_site_target(document, raw_target):
    parsed = urlsplit(raw_target)
    if parsed.scheme or parsed.netloc or raw_target.startswith(("mailto:", "tel:")):
        return None, parsed.fragment
    if raw_target.startswith("#"):
        return document, parsed.fragment

    path = unquote(parsed.path)
    if path.startswith(PAGES_PREFIX):
        resolved = SITE_ROOT / path.removeprefix(PAGES_PREFIX)
    elif path.startswith("/"):
        return None, parsed.fragment
    else:
        resolved = document.parent / path

    resolved = resolved.resolve()
    if resolved.is_dir() or path.endswith("/"):
        resolved /= "index.html"
    return resolved, parsed.fragment


def html_ids(path, cache):
    if path not in cache:
        parser = HtmlLinks()
        parser.feed(path.read_text(encoding="utf-8"))
        cache[path] = parser.ids
    return cache[path]


def main():
    failures = []
    markdown_files = sorted(path for path in ROOT.rglob("*.md") if ".git" not in path.parts)

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
                failures.append(f"{document.relative_to(ROOT)}: link leaves repository: {target}")
            elif not resolved.exists():
                failures.append(f"{document.relative_to(ROOT)}: missing link target: {target}")

    wiki_files = sorted(WIKI_ROOT.glob("*.md")) if WIKI_ROOT.exists() else []
    for document in wiki_files:
        text = document.read_text(encoding="utf-8")
        for raw_target in WIKI_LINK_RE.findall(text):
            page = raw_target.split("|", 1)[0].strip()
            if not page or page.startswith(("http://", "https://")):
                continue
            candidate = WIKI_ROOT / f"{page}.md"
            if not candidate.exists():
                failures.append(f"{document.relative_to(ROOT)}: missing Wiki page: {page}")

    html_files = sorted(SITE_ROOT.rglob("*.html")) if SITE_ROOT.exists() else []
    id_cache = {}
    for document in html_files:
        parser = HtmlLinks()
        parser.feed(document.read_text(encoding="utf-8"))
        id_cache[document] = parser.ids
        for raw_target in parser.targets:
            resolved, fragment = resolve_site_target(document, raw_target)
            if resolved is None:
                continue
            if SITE_ROOT not in resolved.parents and resolved != SITE_ROOT:
                failures.append(f"{document.relative_to(ROOT)}: asset leaves site/: {raw_target}")
                continue
            if not resolved.exists():
                failures.append(f"{document.relative_to(ROOT)}: missing link/asset: {raw_target}")
                continue
            if fragment and resolved.suffix.lower() == ".html" and fragment not in html_ids(resolved, id_cache):
                failures.append(f"{document.relative_to(ROOT)}: missing anchor: {raw_target}")

    for relative in CURRENT_SURFACES:
        document = ROOT / relative
        if not document.exists():
            failures.append(f"{relative}: required current-release surface is missing")
            continue
        text = document.read_text(encoding="utf-8")
        if CURRENT_STABLE not in text:
            failures.append(f"{relative}: does not mention current stable release {CURRENT_STABLE}")
        if PREVIOUS_STABLE in text:
            failures.append(f"{relative}: still presents previous stable release {PREVIOUS_STABLE}")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    print(
        "Documentation OK: "
        f"{len(markdown_files)} Markdown files, {len(wiki_files)} Wiki pages and "
        f"{len(html_files)} HTML pages checked; current-release pointers aligned with {CURRENT_STABLE}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
