#!/usr/bin/env python3
"""Generate release notes from git commits.

Usage:
    python scripts/generate_release_notes.py           # generate files
    python scripts/generate_release_notes.py --dry-run  # preview without writing
    python scripts/generate_release_notes.py --title "My Release"  # custom title
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────

REPO_ROOT = Path(
    subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True
    ).strip()
)
VERSION_FILE = REPO_ROOT / "VERSION"
RELEASE_NOTES_DIR = REPO_ROOT / "Docs" / "ReleaseNotes"
VERSION_READMES_DIR = REPO_ROOT / "Docs" / "VersionREADMEs"

# ── Commit categorisation rules ────────────────────────────────────────────

CATEGORIES = {
    "new_feature": {
        "label": "New Features",
        "prefixes": ["feat:", "feat(", "feature:", "add "],
        "keywords": ["new feature", "implement", "introduce", "create "],
    },
    "bug_fix": {
        "label": "Bug Fixes",
        "prefixes": ["fix:", "fix(", "bugfix:", "hotfix:"],
        "keywords": ["fix ", "fixed", "resolve", "patch "],
    },
    "enhancement": {
        "label": "Enhancements",
        "prefixes": ["enhance:", "improve:", "update:", "refactor:", "perf:"],
        "keywords": ["improve", "upgrade", "optimize", "enhance", "update",
                      "refactor", "use ", "switch", "move", "bump"],
    },
}

SKIP_PATTERNS = [
    re.compile(r"^merge (branch|pull request)", re.IGNORECASE),
    re.compile(r"\[automated\]", re.IGNORECASE),
    re.compile(r"\[skip ci\]", re.IGNORECASE),
]


# ── Helpers ────────────────────────────────────────────────────────────────

def read_base_version() -> str:
    if not VERSION_FILE.exists():
        print(f"ERROR: {VERSION_FILE} not found.", file=sys.stderr)
        sys.exit(1)
    return VERSION_FILE.read_text().strip()


def get_existing_versions() -> list[str]:
    """Return sorted list of versions already released (from JSON filenames)."""
    versions: list[str] = []
    if not RELEASE_NOTES_DIR.exists():
        return versions
    for f in RELEASE_NOTES_DIR.glob("*.json"):
        m = re.search(r"_v(\d+\.\d+\.\d+)\.json$", f.name)
        if m:
            versions.append(m.group(1))
    versions.sort(key=lambda v: tuple(int(x) for x in v.split(".")))
    return versions


def determine_next_version(base: str, existing: list[str]) -> str:
    major, minor, _ = (int(x) for x in base.split("."))
    prefix = f"{major}.{minor}."
    matching_patches = [
        int(v.split(".")[2]) for v in existing if v.startswith(prefix)
    ]
    if matching_patches:
        next_patch = max(matching_patches) + 1
    else:
        # No releases yet for this major.minor — use the base as-is
        next_patch = int(base.split(".")[2])
        # But if that exact version already exists, bump
        if base in existing:
            next_patch += 1
    return f"{major}.{minor}.{next_patch}"


def get_last_version_tag() -> str | None:
    """Find the most recent vX.Y.Z tag."""
    try:
        tags = subprocess.check_output(
            ["git", "tag", "-l", "v*", "--sort=-version:refname"],
            text=True, cwd=REPO_ROOT,
        ).strip()
        if tags:
            return tags.splitlines()[0]
    except subprocess.CalledProcessError:
        pass
    return None


def get_commits_since(tag: str | None) -> list[dict]:
    cmd = ["git", "log", "--pretty=format:%H|%s"]
    if tag:
        cmd.append(f"{tag}..HEAD")
    try:
        output = subprocess.check_output(cmd, text=True, cwd=REPO_ROOT).strip()
    except subprocess.CalledProcessError:
        return []
    if not output:
        return []
    commits = []
    for line in output.splitlines():
        parts = line.split("|", 1)
        if len(parts) == 2:
            commits.append({"hash": parts[0], "subject": parts[1]})
    return commits


def should_skip(subject: str) -> bool:
    return any(p.search(subject) for p in SKIP_PATTERNS)


def clean_subject(subject: str) -> str:
    """Strip conventional-commit prefix for display."""
    cleaned = re.sub(r"^(feat|fix|bugfix|hotfix|enhance|improve|update|refactor|perf)(\(.+?\))?:\s*", "", subject, flags=re.IGNORECASE)
    # Capitalise first letter
    return cleaned[0].upper() + cleaned[1:] if cleaned else cleaned


def categorize_commits(commits: list[dict]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {k: [] for k in CATEGORIES}

    for commit in commits:
        subject = commit["subject"]
        if should_skip(subject):
            continue

        lower = subject.lower()
        matched = False

        for cat_key, cat_info in CATEGORIES.items():
            if any(lower.startswith(p) for p in cat_info["prefixes"]):
                result[cat_key].append(clean_subject(subject))
                matched = True
                break

        if not matched:
            for cat_key, cat_info in CATEGORIES.items():
                if any(kw in lower for kw in cat_info["keywords"]):
                    result[cat_key].append(clean_subject(subject))
                    matched = True
                    break

        if not matched:
            result["enhancement"].append(clean_subject(subject))

    return result


def generate_summary(categories: dict[str, list[str]], version: str) -> str:
    parts = []
    counts = {
        "new_feature": ("new feature", "new features"),
        "enhancement": ("enhancement", "enhancements"),
        "bug_fix": ("bug fix", "bug fixes"),
    }
    for key, (singular, plural) in counts.items():
        n = len(categories.get(key, []))
        if n:
            parts.append(f"{n} {singular if n == 1 else plural}")
    if not parts:
        return f"Release {version}."
    return f"Release {version} includes {', '.join(parts)}."


def build_json(version: str, title: str, summary: str,
               categories: dict[str, list[str]]) -> dict:
    sections = []
    for cat_key, cat_info in CATEGORIES.items():
        items = categories.get(cat_key, [])
        if items:
            sections.append({
                "type": cat_key,
                "label": cat_info["label"],
                "items": items,
            })
    return {
        "version": version,
        "date": str(date.today()),
        "title": title,
        "summary": summary,
        "sections": sections,
    }


def build_markdown(version: str, title: str, summary: str,
                   categories: dict[str, list[str]]) -> str:
    lines = [
        f"# Investron v{version} — {title}",
        "",
        f"**Date:** {date.today()}",
        "",
        "## Overview",
        "",
        summary,
        "",
    ]
    for cat_key, cat_info in CATEGORIES.items():
        items = categories.get(cat_key, [])
        if items:
            lines.append("---")
            lines.append("")
            lines.append(f"## {cat_info['label']}")
            lines.append("")
            for item in items:
                lines.append(f"- {item}")
            lines.append("")
    return "\n".join(lines)


def write_files(version: str, json_data: dict, markdown: str) -> tuple[Path, Path]:
    RELEASE_NOTES_DIR.mkdir(parents=True, exist_ok=True)
    VERSION_READMES_DIR.mkdir(parents=True, exist_ok=True)

    today = date.today()
    json_path = RELEASE_NOTES_DIR / f"{today}_v{version}.json"
    md_path = VERSION_READMES_DIR / f"{today}_v{version}.md"

    json_path.write_text(json.dumps(json_data, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    return json_path, md_path


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate release notes from git history.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files.")
    parser.add_argument("--title", default=None, help="Override release title.")
    args = parser.parse_args()

    base_version = read_base_version()
    existing = get_existing_versions()
    version = determine_next_version(base_version, existing)
    title = args.title or f"v{version}"

    tag = get_last_version_tag()
    commits = get_commits_since(tag)

    if not commits:
        print("No new commits since last release. Nothing to generate.")
        sys.exit(0)

    categories = categorize_commits(commits)
    total_items = sum(len(v) for v in categories.values())
    if total_items == 0:
        print("All commits were filtered out (merge/automated). Nothing to generate.")
        sys.exit(0)

    summary = generate_summary(categories, version)
    json_data = build_json(version, title, summary, categories)
    markdown = build_markdown(version, title, summary, categories)

    if args.dry_run:
        print(f"=== Dry Run: v{version} ===\n")
        print("JSON:")
        print(json.dumps(json_data, indent=2))
        print("\nMarkdown:")
        print(markdown)
        return

    json_path, md_path = write_files(version, json_data, markdown)
    print(f"Generated release notes for v{version}:")
    print(f"  {json_path.relative_to(REPO_ROOT)}")
    print(f"  {md_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
