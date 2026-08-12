"""Fail CI when Spanish prose leaks outside the bilingual Wiki source.

English is the canonical repository language. Spanish is intentionally allowed
under wiki/ so the published GitHub Wiki can keep a complete Spanish edition.
Legacy filenames and compatibility literals may remain; this check inspects
prose rather than paths.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "__pycache__", "wiki"}
SKIP_FILES = {Path("scripts/check-language.py")}
TEXT_SUFFIXES = {
    ".cmd",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".psm1",
    ".py",
    ".sh",
    ".txt",
    ".vbs",
    ".yaml",
    ".yml",
}
TEXT_NAMES = {".env.example", "Dockerfile", "LICENSE", "Makefile"}

SPANISH_PATTERNS = [
    re.compile(r"[áéíóúüñ¿¡]", re.IGNORECASE),
    re.compile(
        r"\b(?:"
        r"no coincide|se requieren?|son obligatorios?|no cumple|"
        r"ejecutor(?:a)?|preparando|levantando|falta(?:n)?|"
        r"por favor|no se puede|no existe|debe contener|debe ser|"
        r"permisos administrativos|archivo|carpeta|contraseña|"
        r"usuario|guardado|restaurar|descargar|subir|mundo|"
        r"motivo del|versi[oó]n estable"
        r")\b",
        re.IGNORECASE,
    ),
]

# A line containing several of these words is almost certainly Spanish prose.
# Requiring three hits avoids false positives from isolated identifiers or
# proper names while catching unaccented comments such as "bajo un nuevo...".
SPANISH_STOPWORDS = {
    "aqui",
    "antes",
    "bajo",
    "cada",
    "cuando",
    "debe",
    "deben",
    "del",
    "despues",
    "donde",
    "el",
    "esta",
    "este",
    "fichero",
    "hasta",
    "la",
    "las",
    "los",
    "nueva",
    "nuevo",
    "para",
    "pero",
    "por",
    "porque",
    "que",
    "se",
    "segunda",
    "si",
    "sin",
    "solo",
    "tambien",
    "una",
    "uno",
    "ya",
}

# Language selectors are metadata, not prose. Keep the localized label itself
# so bilingual navigation remains obvious on the English site.
ALLOWED_INLINE_LABELS = ("Español",)


def is_text_file(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if relative in SKIP_FILES:
        return False
    if any(part in SKIP_DIRS for part in relative.parts[:-1]):
        return False
    return path.name in TEXT_NAMES or path.suffix.lower() in TEXT_SUFFIXES


def strip_diacritics(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def checkable_line(line: str) -> str:
    cleaned = line
    for label in ALLOWED_INLINE_LABELS:
        cleaned = cleaned.replace(label, "Spanish")
    return cleaned


def looks_like_spanish_prose(line: str) -> bool:
    candidate = checkable_line(line)
    if any(pattern.search(candidate) for pattern in SPANISH_PATTERNS):
        return True
    normalized = strip_diacritics(candidate).casefold()
    words = re.findall(r"[a-z]+", normalized)
    return sum(word in SPANISH_STOPWORDS for word in words) >= 3


def main() -> int:
    findings: list[str] = []
    checked = 0
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or not is_text_file(path):
            continue
        checked += 1
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if looks_like_spanish_prose(line):
                findings.append(
                    f"{path.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )

    if findings:
        print("Spanish prose found outside wiki/:")
        print("\n".join(findings))
        return 1

    print(f"Language check OK: {checked} text files checked; Spanish is confined to wiki/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
