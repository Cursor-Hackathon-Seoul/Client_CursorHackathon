---
name: git-master
description: >-
  Applies Bobmoo Git conventions from .cursor/conventions.md: branch names,
  commit messages, PR titles, issue titles/bodies, labels/priority heuristics.
  Use for 커밋, 브랜치, PR, 푸시, 이슈. Linear 연동 문구는 적용하지 않는다 (GitHub만).
---

# Git Master (Bobmoo Convention)

**단일 기준:** [`.cursor/conventions.md`](../../conventions.md). Prefix 표·네이밍 표·이슈/PR 바디 정책·Priority·Label 휴리스틱은 그 문서를 따른다.

**범위:** `conventions.md`에 Linear가 함께 적혀 있어도, **이 스킬 적용 시 Linear 관련 요구는 무시한다.** 이슈·PR 연동은 **GitHub**만 기준으로 한다.

## When to Use

- 브랜치 생성, 커밋 메시지, PR 제목·본문, GitHub 이슈 제목·바디 작성/검토
- 사용자가 Git 관련 작업을 요청할 때

## Code Convention

- Swift: [StyleShare Swift Style Guide](https://github.com/StyleShare/swift-style-guide)

## 형식 요약 (상세·예시는 conventions.md)

| 대상 | 형식 |
|------|------|
| **이슈 제목** | `[Prefix] <작업내용>` (Prefix는 TitleCase 풀 단어, 표는 conventions.md) |
| **브랜치** | `prefix/#이슈번호-브랜치네임` |
| **커밋** | `prefix: #이슈번호 커밋내용` |
| **PR 제목** | `Prefix/#이슈번호 제목` |

- 이슈 제목 끝에 `하기` 붙이지 않음.
- 커밋: 한국어 중심, 기술 용어만 영어 혼용, **영어-only 금지**, 서명·광고 문구 금지.

### 커밋 전 3체크

1. 브랜치명에서 이슈번호 확인
2. 메시지가 `prefix: #이슈번호 …` 패턴 준수
3. 메시지가 staged 변경과 일치  

실패 시 커밋하지 말고 정정안을 먼저 제시.

## 이슈 바디

- `.github/ISSUE_TEMPLATE/issue_template.md` 구조(작업 페이지 캡쳐, To-Do) 유지. 세부는 conventions.md.

## PR 바디

- `.github/PULL_REQUEST_TEMPLATE.md`가 있으면 그 구조.
- conventions.md의 필수 항목을 따르되, **연결된 이슈는 GitHub 이슈 URL**만 기입하면 된다 (Linear URL·상호 링크 문구는 생략).
- `구현 의도 / 결정 이유`는 구현이 있는 변경에 반드시 포함.

## MUST DO

- 커밋에 이슈 번호 포함. 이슈 없이 브랜치 생성하지 않음.
- 브랜치·커밋 lowercase prefix와 PR TitleCase prefix를 conventions 표에 맞게 일치.
- Swift는 StyleShare 기준으로 리뷰·제안.
- 사용자 **명시 허락 전 push 금지.**
- PR에 assignee `@me`, 라벨 최소 1개 (라벨은 conventions.md Label 휴리스틱 참고).

## MUST NOT DO

- 이슈 번호 없는 커밋, 임의 브랜치명(`test`, `temp`, `fix2` 등).
- PR 제목에서 Prefix/이슈번호 누락, 패턴 어긴 채 커밋 강행.
- 영어-only 커밋, 에이전트/봇 서명·도구 홍보 문구.
