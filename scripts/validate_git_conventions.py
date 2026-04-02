#!/usr/bin/env python3
"""
Bobmoo Git 컨벤션 검증 (.cursor/conventions.md 기준).
--self-test: 형식 단위 테스트 (반드시 통과)
--repo: 현재 브랜치/마지막 커밋·필수 파일 존재 여부 점검
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONVENTIONS_MD = ROOT / ".cursor" / "conventions.md"

BRANCH_PREFIXES = r"feat|fix|refactor|chore|docs|test"
COMMIT_PREFIXES = BRANCH_PREFIXES

# 브랜치: prefix/#123-slug
RE_BRANCH = re.compile(
    rf"^({BRANCH_PREFIXES})/#\d+-[a-z0-9]+(?:-[a-z0-9]+)*$"
)
# 커밋: prefix: #123 본문 (본문에 한글 1자 이상 — 영어-only 금지)
RE_COMMIT_HEAD = re.compile(rf"^({COMMIT_PREFIXES}): #\d+ (.+)$", re.DOTALL)

# PR 제목: Feat/#123 제목
RE_PR = re.compile(
    r"^(Feat|Fix|Refactor|Chore|Docs|Test)/#\d+ .+"
)
# 이슈 제목: [Feature] 제목 (표의 풀 단어)
RE_ISSUE = re.compile(
    r"^\[(Feature|Bug|Refactor|Chore|Docs|Test)\] .+"
)

EXEMPT_BRANCHES = frozenset({"main", "master", "develop"})

BOT_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"Co-authored-by:",
        r"Generated with",
        r"🤖",
        r"\bclaude\b",
        r"\bcursor\b",
        r"Signed-off-by:.*bot",
    ]
]


def has_hangul(s: str) -> bool:
    return bool(re.search(r"[\uac00-\ud7a3]", s))


def validate_branch(name: str, exempt: frozenset[str] | None = None) -> tuple[bool, str]:
    exempt = exempt or EXEMPT_BRANCHES
    if name in exempt:
        return True, "exempt default branch"
    if RE_BRANCH.match(name):
        return True, "ok"
    return False, f"브랜치는 '{BRANCH_PREFIXES}/#이슈-slug' 형식이어야 함 (현재: {name!r})"


def validate_commit_message(msg: str) -> tuple[bool, str]:
    msg = msg.strip()
    m = RE_COMMIT_HEAD.match(msg)
    if not m:
        return False, "커밋은 'prefix: #번호 한글_중심_설명' 형식이어야 함"
    body = m.group(2).strip().split("\n")[0]
    if not has_hangul(body):
        return False, "커밋 첫 줄 본문에 한글이 없음 (영어-only 금지)"
    for bp in BOT_PATTERNS:
        if bp.search(msg):
            return False, f"봇/도구 서명류 문구 포함: {bp.pattern!r}"
    return True, "ok"


def validate_pr_title(title: str) -> tuple[bool, str]:
    if RE_PR.match(title.strip()):
        return True, "ok"
    return False, "PR 제목은 'Prefix/#번호 제목' (Prefix는 Feat|Fix|…)"


def validate_issue_title(title: str) -> tuple[bool, str]:
    if RE_ISSUE.match(title.strip()):
        return True, "ok"
    return False, "이슈 제목은 '[Feature] …' 등 표의 TitleCase 풀 단어"


def run_self_tests() -> list[str]:
    errors: list[str] = []

    def check(ok: bool, name: str, detail: str = "") -> None:
        if not ok:
            errors.append(f"{name}: {detail}")

    # 브랜치
    ok, _ = validate_branch("main")
    check(ok, "branch main exempt")
    ok, _ = validate_branch("feat/#1-login-api")
    check(ok, "branch good feat/#1-login-api", "expected ok")
    ok, d = validate_branch("feature/foo")
    check(not ok, "branch bad feature/foo", d)

    # 커밋
    ok, _ = validate_commit_message("feat: #1 로그인 추가")
    check(ok, "commit good Korean")
    ok, d = validate_commit_message("feat: #1 add login")
    check(not ok, "commit bad English-only", d)
    ok, d = validate_commit_message("bad message")
    check(not ok, "commit bad format", d)

    # PR
    ok, _ = validate_pr_title("Feat/#1 로그인 처리")
    check(ok, "pr good")
    ok, d = validate_pr_title("feat/#1 title")
    check(not ok, "pr bad lowercase prefix", d)

    # 이슈
    ok, _ = validate_issue_title("[Feature] 로그인 화면")
    check(ok, "issue good")
    ok, d = validate_issue_title("[Feat] x")
    check(not ok, "issue bad Feat in brackets", d)

    return errors


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def check_repo(strict_commit: bool) -> list[str]:
    issues: list[str] = []

    if not CONVENTIONS_MD.is_file():
        issues.append(".cursor/conventions.md 없음")

    issue_tpl = ROOT / ".github" / "ISSUE_TEMPLATE" / "issue_template.md"
    pr_tpl = ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"
    if not issue_tpl.is_file():
        issues.append(f"없음: {issue_tpl.relative_to(ROOT)} (conventions 이슈 바디)")
    else:
        text = issue_tpl.read_text(encoding="utf-8")
        if "작업 페이지 캡쳐" not in text or "To-Do" not in text:
            issues.append("issue_template.md에 필수 섹션(작업 페이지 캡쳐, To-Do) 누락")

    if not pr_tpl.is_file():
        issues.append(f"없음: {pr_tpl.relative_to(ROOT)} (conventions PR 바디)")

    branch = git("branch", "--show-current")
    ok, detail = validate_branch(branch)
    if not ok:
        issues.append(f"브랜치: {detail}")

    msg = git("log", "-1", "--format=%B")
    ok, detail = validate_commit_message(msg)
    if not ok:
        if strict_commit and branch not in EXEMPT_BRANCHES:
            issues.append(f"마지막 커밋: {detail}")
        elif not ok:
            # 기본 브랜치에서는 경고만
            if branch in EXEMPT_BRANCHES:
                issues.append(f"[경고] 마지막 커밋이 컨벤션과 다름 ({detail}) — main 등 초기 커밋은 예외 가능")
            else:
                issues.append(f"마지막 커밋: {detail}")

    return issues


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--repo", action="store_true")
    ap.add_argument(
        "--strict-commit",
        action="store_true",
        help="기본 브랜치라도 마지막 커밋 형식 실패 시 오류로 처리",
    )
    args = ap.parse_args()

    if not args.self_test and not args.repo:
        args.self_test = True
        args.repo = True

    exit_code = 0

    if args.self_test:
        errs = run_self_tests()
        if errs:
            print("--self-test 실패:")
            for e in errs:
                print(" ", e)
            exit_code = 1
        else:
            print("--self-test: OK (형식 규칙 일치)")

    if args.repo:
        issues = check_repo(strict_commit=args.strict_commit)
        hard = [i for i in issues if not i.startswith("[경고]")]
        warns = [i for i in issues if i.startswith("[경고]")]

        if hard:
            print("--repo 실패:")
            for i in hard:
                print(" ", i)
            exit_code = 1
        else:
            print("--repo: 필수 경로/브랜치 규칙 OK")

        for w in warns:
            print(w)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
