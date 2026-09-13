#!/usr/bin/env python3
"""Daily refresh of the contributions section in the profile README.

Fetches merged / open PRs authored by HUAN2022A from the GitHub search API
(excluding PRs inside HUAN2022A's own repositories), renders a markdown
block, and rewrites ONLY the span between:

    <!--START_SECTION:contrib--> ... <!--END_SECTION:contrib-->

Everything outside the two markers is preserved byte-for-byte, including the
original newline style (LF / CRLF).

Standard library only: urllib / json / re / sys / argparse / os.

Usage:
    python scripts/update_contrib.py [--repo-dir PATH] [--check]

    --check    dry-run: validate the markers exist, print the block that
               would be written, exit 1 without writing when the markers
               are missing.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

GITHUB_USER = "HUAN2022A"
SEARCH_API = "https://api.github.com/search/issues"
PER_PAGE = 100
MAX_PAGES = 10  # GitHub search API caps results at 1000 anyway
REQUEST_TIMEOUT = 30
MERGED_LIMIT = 10

START_MARKER = "<!--START_SECTION:contrib-->"
END_MARKER = "<!--END_SECTION:contrib-->"

# Hard-coded entry: proposal adopted by upstream maintainers.
ADOPTED_LINE = (
    "- [microsoft/agent-framework#7326]"
    "(https://github.com/microsoft/agent-framework/pull/7326) "
    "— replayed approval calls 去重修复，方案被吸收进官方 PR "
    "[#7345](https://github.com/microsoft/agent-framework/pull/7345)"
)

_REPO_RE = re.compile(r"/repos/([^/]+/[^/]+?)(?:/|$)")
_OWN_URL_FRAGMENT = "/repos/" + GITHUB_USER + "/"


def fail(message):
    sys.stderr.write("update_contrib: " + message + "\n")
    sys.exit(1)


def build_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": GITHUB_USER + "-profile-contrib-updater",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers, bool(token)


def fetch_prs(query, headers):
    """Return every search hit for `query`, following per_page=100 pages."""
    items = []
    for page in range(1, MAX_PAGES + 1):
        url = SEARCH_API + "?" + urllib.parse.urlencode(
            {"q": query, "per_page": PER_PAGE, "page": page}
        )
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            fail(
                "GitHub API HTTP %d (%s) for query %r page %d"
                % (exc.code, exc.reason, query, page)
            )
        except urllib.error.URLError as exc:
            fail(
                "GitHub API unreachable (%s) for query %r page %d"
                % (exc.reason, query, page)
            )
        batch = payload.get("items") or []
        items.extend(batch)
        if len(batch) < PER_PAGE:
            break
    return items


def is_own_repo(item):
    """PRs inside HUAN2022A's own repositories are not external contributions."""
    return _OWN_URL_FRAGMENT in (item.get("repository_url") or "")


def to_entry(item):
    match = _REPO_RE.search(item.get("repository_url") or "")
    repo = match.group(1) if match else "unknown/unknown"
    number = item.get("number")
    url = item.get("html_url") or ("https://github.com/%s/pull/%s" % (repo, number))
    title = re.sub(r"\s+", " ", (item.get("title") or "").strip())
    return {
        "repo": repo,
        "number": number,
        "url": url,
        "title": title,
        "updated_at": item.get("updated_at") or "",
    }


def entry_line(entry):
    return "- [%s#%s](%s) — %s" % (
        entry["repo"],
        entry["number"],
        entry["url"],
        entry["title"],
    )


def render_block(merged, open_prs):
    lines = []

    lines.append("**✅ 已合并 Merged**")
    lines.append("")
    if merged:
        for entry in merged[:MERGED_LIMIT]:
            lines.append(entry_line(entry))
        if len(merged) > MERGED_LIMIT:
            lines.append("- 等共 %d 个" % len(merged))
    else:
        lines.append("- 暂无")

    lines.append("")
    lines.append("**🌟 方案被维护者采纳 Adopted**")
    lines.append("")
    lines.append(ADOPTED_LINE)

    lines.append("")
    lines.append("**🚧 进行中 In review**")
    lines.append("")
    if open_prs:
        groups = {}
        for entry in open_prs:
            groups.setdefault(entry["repo"], []).append(entry)
        ordered = sorted(
            groups.items(),
            key=lambda pair: max(e["updated_at"] for e in pair[1]),
            reverse=True,
        )
        for repo, entries in ordered:
            lines.append("- **[%s](https://github.com/%s)**：" % (repo, repo))
            for entry in sorted(entries, key=lambda e: e["updated_at"], reverse=True):
                lines.append("  " + entry_line(entry))
    else:
        lines.append("- 暂无")

    return "\n".join(lines)


def collect(headers):
    merged_raw = fetch_prs("author:%s type:pr is:merged" % GITHUB_USER, headers)
    open_raw = fetch_prs("author:%s type:pr state:open" % GITHUB_USER, headers)
    merged = [to_entry(i) for i in merged_raw if not is_own_repo(i)]
    open_prs = [to_entry(i) for i in open_raw if not is_own_repo(i)]
    merged.sort(key=lambda e: e["updated_at"], reverse=True)
    return merged, open_prs


def main():
    parser = argparse.ArgumentParser(
        description="Refresh the contributions section of the profile README."
    )
    parser.add_argument(
        "--repo-dir",
        default=".",
        help="path to the repository checkout containing README.md (default: .)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="dry-run: print the generated block without writing; "
        "exit 1 if the markers are missing",
    )
    args = parser.parse_args()

    readme_path = os.path.join(args.repo_dir, "README.md")
    try:
        with open(readme_path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        fail("cannot read %s: %s" % (readme_path, exc))
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        fail("%s is not valid UTF-8: %s" % (readme_path, exc))

    start = text.find(START_MARKER)
    end = text.find(END_MARKER, start + len(START_MARKER)) if start != -1 else -1
    if start == -1 or end == -1:
        fail(
            "markers missing in %s: need %s / %s"
            % (readme_path, START_MARKER, END_MARKER)
        )

    headers, authed = build_headers()
    merged, open_prs = collect(headers)

    block = render_block(merged, open_prs)
    print(
        "[info] %d merged / %d open external PRs (own-repo filtered out, auth=%s)"
        % (len(merged), len(open_prs), "yes" if authed else "anonymous")
    )

    if args.check:
        print("--- block that would be written between markers ---")
        print(block)
        print("--- end of block (check mode: %s not modified) ---" % readme_path)
        return 0

    eol = "\r\n" if "\r\n" in text else "\n"
    inner = eol + block.replace("\n", eol) + eol
    new_text = text[: start + len(START_MARKER)] + inner + text[end:]
    try:
        with open(readme_path, "wb") as fh:
            fh.write(new_text.encode("utf-8"))
    except OSError as exc:
        fail("cannot write %s: %s" % (readme_path, exc))
    print("[info] updated %s" % readme_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
