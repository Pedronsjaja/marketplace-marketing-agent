"""Heuristic public-tree audit: no content values are printed. Not a DLP guarantee."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = {
    "credential": re.compile(r"(?:ghp_|github_pat_|sk-proj-)[A-Za-z0-9_-]{12,}|-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
    "personal_email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"\+\d{1,3}[\s()-]*\d[\d\s()-]{7,}\d|\(\d{2}\)\s*\d{4,5}[- ]\d{4}"),
    "personal_path": re.compile(r"[A-Za-z]:[/\\](?:Users|Marketing)[/\\_]", re.I),
}
BAD_PARTS = {"private", "sessions", "cookies", "profiles", "screenshots", "browser-data"}
BAD_NAMES = {"controle.csv", "auth.json", ".env"}
BINARY_SUFFIXES = {".png",".jpg",".jpeg",".webp",".har",".db",".sqlite",".pem",".key"}
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.invalid"}


def findings(path, content):
    problems=[]
    for name, pattern in PATTERNS.items():
        for match in pattern.finditer(content):
            if name=="personal_email" and match.group().split("@")[-1] in ALLOWED_EMAIL_DOMAINS:
                continue
            problems.append(name)
            break
    return problems


def main():
    result=subprocess.run(["git","ls-files","-z","--cached","--others","--exclude-standard"],cwd=ROOT,capture_output=True,check=True)
    paths=sorted(set(p for p in result.stdout.decode("utf-8").split("\0") if p))
    errors=[]
    for name in paths:
        path=Path(name)
        if any(part.lower() in BAD_PARTS for part in path.parts) or path.name.lower() in BAD_NAMES or path.suffix.lower() in BINARY_SUFFIXES:
            errors.append((name,"forbidden file type/location"))
            continue
        full=ROOT/path
        if full.is_symlink():
            errors.append((name,"symlink requires manual review"));continue
        try:content=full.read_text(encoding="utf-8-sig")
        except (UnicodeError,OSError):
            errors.append((name,"unreadable/non-text public file"));continue
        errors.extend((name,reason) for reason in findings(path,content))
    for name,reason in errors:
        print(f"{name}: {reason}")
    print(f"Audited {len(paths)} public candidate files; findings={len(errors)}")
    return int(bool(errors))


if __name__=="__main__":
    raise SystemExit(main())
