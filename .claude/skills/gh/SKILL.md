---
name: gh
description: "Expert guide for utilizing the GitHub CLI (gh) and the gh pr-review extension. Use this when interacting with issues, managing pull requests, viewing review threads, or automating repository pipelines via the terminal."
argument-hint: "[issue|pr|repo] [options]"
---

# GitHub CLI (`gh`) & `gh pr-review` Workflow Guidelines

When the user requests repository interaction, issue tracking, or PR manipulation, you must execute these operations via the terminal using the official `gh` CLI or the `gh pr-review` extension.

### Core Execution Rules

1. **No Hedging:** Provide exact command invocations without speculative commentary.
1. **Prefer Scripting Over Parsing:** Always use the `--json` + `--jq` flags when extracting data from `gh` to handle automation. Do not scrape raw text output.
1. **Explicit Repo Targeting:** When handling inline review threads with the `gh pr-review` extension, always append the `-R owner/repo` flag explicitly.
1. **Thread Resolution:** Use `review view` to isolate exact GraphQL node IDs (`PRRT_...`) before attempting thread replies or resolutions.

## Parameter Routing

If the user passes manual variables via a slash command (`$ARGUMENTS`), evaluate their intent:

- If `$0` is `issue`, prioritize sections covering **Issues (`gh issue`)**.
- If `$0` is `pr`, prioritize sections covering **Pull Requests (`gh pr`)**.
- If no arguments are provided, use the global repo context.

______________________________________________________________________

## Authentication & Environment Variables

```bash
gh auth login [--hostname HOST] [--with-token] [--web] [--git-protocol ssh|https]
gh auth status
gh auth refresh [--scopes SCOPES]
```

| Variable                    | Purpose                              |
| --------------------------- | ------------------------------------ |
| `GH_TOKEN` / `GITHUB_TOKEN` | Auth token (GH_TOKEN wins)           |
| `GH_HOST`                   | GitHub hostname (Enterprise)         |
| `GH_REPO`                   | Override repo as `[HOST/]OWNER/REPO` |
| `GH_EDITOR`                 | Editor for text input                |
| `GH_BROWSER`                | Browser for `--web`                  |
| `GH_DEBUG`                  | Verbose output; `"api"` shows HTTP   |
| `GH_PAGER`                  | Terminal pager                       |
| `GH_FORCE_TTY`              | Force terminal output when piped     |
| `NO_COLOR` / `CLICOLOR=0`   | Disable colors                       |

______________________________________________________________________

## Pull Requests (`gh pr`)

### Create

```bash
gh pr create \
  --title "Title" \
  --body "Description" \
  --body-file FILE \          # or "-" for stdin
  --base BRANCH \             # base branch
  --head BRANCH \             # head branch
  --draft \
  --reviewer USER,TEAM \
  --assignee LOGIN \          # @me for self
  --label "bug,enhancement" \
  --project "Board" \
  --milestone "v1.0" \
  --fill \                    # auto-fill from commits
  --no-maintainer-edit \
  --web                       # open browser instead
```

### List

```bash
gh pr list \
  --state open|closed|merged|all \   # default: open
  --author HANDLE \
  --assignee LOGIN \
  --label LABELS \
  --base BRANCH \
  --head BRANCH \
  --search "QUERY" \           # GitHub search syntax
  --draft true|false \
  --limit NUM \                # default: 30
  --json FIELDS \
  --jq EXPR \
  --template TEXT \
  --web
```

### View / Diff / Checks

```bash
gh pr view [NUMBER|URL|BRANCH] [--comments] [--json FIELDS] [--jq EXPR] [--web]
gh pr diff [NUMBER|URL|BRANCH]
gh pr checks [NUMBER|URL|BRANCH]
```

### Merge

```bash
gh pr merge [NUMBER|URL|BRANCH] \
  --merge \                    # merge commit (default)
  --rebase \
  --squash \
  --delete-branch \
  --auto \                     # enable auto-merge
  --disable-auto \
  --admin \                    # bypass required reviews
  --subject TEXT \
  --body TEXT \
  --match-head-commit SHA
```

### Review (top-level only - use gh pr-review for inline threads)

```bash
gh pr review [NUMBER|URL|BRANCH] --approve|--request-changes|--comment --body "msg"
```

### Other pr commands

```bash
gh pr checkout NUMBER|URL|BRANCH
gh pr close NUMBER|URL|BRANCH
gh pr reopen NUMBER|URL|BRANCH
gh pr ready NUMBER|URL|BRANCH         # mark draft as ready
gh pr edit NUMBER|URL|BRANCH \
  --title TEXT --body TEXT \
  --add-label L --remove-label L \
  --add-assignee LOGIN --remove-assignee LOGIN \
  --add-reviewer USER --remove-reviewer USER \
  --milestone NAME --base BRANCH
gh pr status
```

PR selectors: number (`123`), URL, or branch name (`feature` or `OWNER:feature`).

______________________________________________________________________

## Issues (`gh issue`)

```bash
gh issue create \
  --title TEXT --body TEXT --body-file FILE \
  --assignee LOGIN --label LABELS \
  --project NAMES --milestone NAME --web

gh issue list \
  --state open|closed|all \
  --assignee LOGIN --author HANDLE --label LABELS \
  --mention HANDLE --milestone NAME \
  --search QUERY --limit NUM \
  --json FIELDS --jq EXPR --web

gh issue view NUMBER|URL [--comments] [--json FIELDS] [--web]
gh issue close NUMBER|URL [--comment TEXT] [--reason completed|not_planned]
gh issue reopen NUMBER|URL [--comment TEXT]
gh issue edit NUMBER|URL \
  --title TEXT --body TEXT \
  --add-label L --remove-label L \
  --add-assignee LOGIN --remove-assignee LOGIN \
  --milestone NAME
gh issue comment NUMBER|URL --body TEXT [--body-file FILE] [--edit-last]
gh issue delete NUMBER|URL [--yes]
gh issue transfer NUMBER|URL DEST_REPO
gh issue status
```

______________________________________________________________________

## Repositories (`gh repo`)

```bash
gh repo create [NAME] \
  --public|--private|--internal \
  --description TEXT --homepage URL \
  --gitignore TEMPLATE --license TEMPLATE \
  --team TEAM --template TEMPLATE \
  --source PATH --clone --push \
  --disable-issues --disable-wiki

gh repo clone OWNER/REPO [DIR] [-- git-flags] [--upstream-remote-name NAME]
gh repo view [OWNER/REPO] [--web] [--json FIELDS]
gh repo fork [OWNER/REPO] [--clone] [--remote] [--fork-name NAME] [--org ORG]
gh repo list [OWNER] \
  --source --fork --archived --private --public \
  --language LANG --limit NUM --json FIELDS --jq EXPR
gh repo edit [OWNER/REPO] \
  --description TEXT --homepage URL \
  --visibility public|private|internal \
  --enable-issues --disable-issues \
  --enable-wiki --disable-wiki \
  --default-branch BRANCH \
  --delete-branch-on-merge \
  --enable-merge-commit --enable-rebase-merge --enable-squash-merge \
  --enable-auto-merge
gh repo sync [OWNER/REPO] [--branch BRANCH] [--force] [--source SOURCE]
gh repo rename [NEW_NAME] [--yes]
gh repo delete [OWNER/REPO] [--yes]
gh repo archive [OWNER/REPO] [--yes]
gh repo deploy-key list|add|delete
```

______________________________________________________________________

## Releases (`gh release`)

```bash
gh release create TAG [FILES...] \
  --title TEXT --notes TEXT --notes-file FILE \
  --draft --prerelease \
  --target BRANCH|SHA \
  --generate-notes \
  --notes-start-tag TAG \
  --discussion-category CATEGORY \
  --latest --legacy

gh release list [--limit NUM] [--json FIELDS] [--jq EXPR]
gh release view [TAG] [--web] [--json FIELDS]
gh release edit TAG \
  --title TEXT --notes TEXT --draft --prerelease --latest --tag NEW_TAG
gh release download [TAG] \
  --pattern GLOB --dir DIR --clobber [--output FILE]
gh release upload TAG FILES... [--clobber]
gh release delete TAG [--yes] [--cleanup-tag]
gh release delete-asset TAG ASSET_NAME [--yes]
```

______________________________________________________________________

## Workflows & Runs (`gh workflow` / `gh run`)

```bash
gh workflow list [--all] [--json FIELDS]
gh workflow view [WORKFLOW] [--web] [--yaml] [--ref BRANCH]
gh workflow enable|disable [WORKFLOW]
gh workflow run WORKFLOW [--ref BRANCH] [-f KEY=VALUE...]   # workflow_dispatch

gh run list \
  --workflow WORKFLOW \
  --actor HANDLE --branch BRANCH \
  --event push|pull_request|... \
  --status queued|in_progress|completed|success|failure|... \
  --limit NUM --json FIELDS --jq EXPR

gh run view [RUN_ID] [--job JOB_ID] [--log] [--log-failed] [--web]
gh run watch [RUN_ID] [--interval SECONDS] [--exit-status]
gh run rerun [RUN_ID] [--failed] [--job JOB_ID]
gh run cancel [RUN_ID]
gh run download [RUN_ID] [-n ARTIFACT_NAME] [-D DIR] [--pattern GLOB]
```

`WORKFLOW` = filename (`ci.yml`), numeric ID, or display name.

______________________________________________________________________

## Gists, Secrets, Variables, Labels

```bash
# Gists
gh gist create [FILES] [--public] [--desc TEXT] [--filename NAME]
gh gist list [--public|--secret] [--limit NUM] [--json FIELDS]
gh gist view GIST_ID [--filename FILE] [--raw] [--web]
gh gist edit GIST_ID [FILE] [--add FILE] [--remove FILE] [--desc TEXT]
gh gist delete GIST_ID [--yes]
gh gist clone GIST_ID [DIR]

# Secrets
gh secret list [--env ENV] [--org ORG] [--app dependabot|actions|codespaces]
gh secret set NAME [--body TEXT] [--env ENV] [--org ORG] [--repos "OWNER/REPO,..."]
gh secret delete NAME [--env ENV] [--org ORG]

# Variables (unencrypted Actions env vars)
gh variable list [--env ENV] [--org ORG]
gh variable set NAME --body VALUE [--env ENV] [--org ORG]
gh variable delete NAME [--env ENV] [--org ORG]

# Labels
gh label list [--search TEXT] [--sort name|created] [--json FIELDS]
gh label create NAME --color HEX --description TEXT [--force]
gh label edit NAME [--name NEW] [--color HEX] [--description TEXT]
gh label delete NAME [--yes]
gh label clone SOURCE_REPO [--force]
```

______________________________________________________________________

## Search

```bash
gh search repos QUERY [--language LANG] [--topic TOPIC] \
  --owner OWNER --stars ">100" --limit NUM --json FIELDS

gh search issues QUERY [--repo OWNER/REPO] \
  --state open|closed --label LABELS \
  --assignee LOGIN --author HANDLE --limit NUM --json FIELDS

gh search prs QUERY [--repo OWNER/REPO] \
  --state open|closed|merged --draft true|false \
  --base BRANCH --head BRANCH --limit NUM --json FIELDS
```

______________________________________________________________________

## `gh api` - Direct REST/GraphQL Access

```bash
gh api ENDPOINT \
  --method GET|POST|PUT|PATCH|DELETE \  # default: GET (POST if fields provided)
  --field KEY=VALUE \      # typed: true/false/null/int auto-cast; @FILE reads file
  --raw-field KEY=VALUE \  # always string
  --header 'Key: Value' \
  --input FILE \           # body from file; "-" for stdin
  --paginate \             # fetch all pages
  --jq EXPR \
  --template TEXT \
  --cache DURATION \       # e.g. "3600s", "60m", "1h"
  --hostname HOST
```

Placeholders `{owner}`, `{repo}`, `{branch}` auto-fill from local git context.

```bash
# REST
gh api repos/{owner}/{repo}/releases --paginate
gh api repos/{owner}/{repo}/issues/123/comments -f body='Comment'

# GraphQL
gh api graphql -f query='
  query($owner:String!, $name:String!) {
    repository(owner:$owner, name:$name) {
      issues(last:5, states:OPEN) { nodes { number title } }
    }
  }
' -F owner='{owner}' -F name='{repo}'

# Paginated GraphQL
gh api graphql --paginate -f query='
  query($endCursor:String) {
    viewer {
      repositories(first:100, after:$endCursor) {
        nodes { nameWithOwner }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
'
```

______________________________________________________________________

## Output Formatting

```bash
# List available fields
gh pr list --json

# JSON + jq (no jq binary needed)
gh pr list --json number,title --jq '.[] | "#\(.number) \(.title)"'
gh pr list --json number,labels --jq '.[] | select(.labels[].name == "bug") | .number'

# Go template
gh pr list --json number,title,author \
  --template '{{range .}}{{tablerow (printf "#%v" .number) .title .author.login}}{{end}}{{tablerender}}'
```

Template functions: `autocolor`, `color`, `join`, `pluck`, `tablerow`, `tablerender`, `timeago`, `timefmt`, `truncate`.

______________________________________________________________________

## Scripting Patterns

```bash
# Current PR number
gh pr view --json number --jq '.number'

# Check if PR exists for current branch
gh pr view --json number 2>/dev/null && echo "exists" || echo "none"

# Latest release tag
gh release list --limit 1 --json tagName --jq '.[0].tagName'

# Batch close stale issues
gh issue list --state open --label stale --json number --jq '.[].number' \
  | xargs -I{} gh issue close {}

# Watch run until done, propagate exit code
gh run watch RUN_ID --exit-status

# Headless CI
GH_TOKEN="$TOKEN" gh pr create --title "..." --body "..."
```

______________________________________________________________________

## Other Commands

```bash
gh browse [FILE|DIR|COMMIT] [--branch BRANCH] [--settings] [--issues] [--actions]

gh alias list
gh alias set co 'pr checkout'
gh alias delete co
gh alias expand co

gh config list
gh config set git_protocol ssh|https
gh config set editor "code --wait"
gh config set pager "less -F"

gh extension list
gh extension install OWNER/REPO
gh extension upgrade --all
gh extension remove OWNER/REPO

gh status [--exclude REPOS] [--org ORG]

-R, --repo OWNER/REPO     # global flag: override target repo
```

______________________________________________________________________

## `gh pr-review` Extension - Inline Review Threads

`gh pr review` only handles top-level review feedback. Use `gh pr-review` for inline comment threads.

```bash
gh extension install agynio/gh-pr-review
gh extension upgrade agynio/gh-pr-review
```

All IDs use GraphQL format: `PRR_...` reviews, `PRRT_...` threads, `PRRC_...` comments. Always pass `-R owner/repo`.

### `review --start` - Open a pending review

```bash
gh pr-review review --start [NUMBER|URL] -R owner/repo [--commit SHA]
# → { "id": "PRR_...", "state": "PENDING" }
```

The `id` is required for `--add-comment` and `--submit`.

### `review --add-comment` - Attach inline comment to pending review

```bash
gh pr-review review --add-comment [NUMBER|URL] \
  -R owner/repo \
  --review-id PRR_... \
  --path src/file.py \
  --line 42 \
  --body "comment" \
  [--side LEFT|RIGHT] \        # default: RIGHT
  [--start-line N] \           # multi-line range
  [--start-side LEFT|RIGHT]
# → { "id": "PRRT_...", "path": "...", "is_outdated": false, "line": 42 }
```

### `review view` - Full review context in one call

```bash
gh pr-review review view [NUMBER|URL] \
  -R owner/repo \
  [--pr NUMBER] \
  [--reviewer LOGIN] \
  [--states APPROVED,CHANGES_REQUESTED,COMMENTED,DISMISSED] \
  [--unresolved] \
  [--not_outdated] \
  [--tail N] \                      # keep last N replies per thread
  [--include-comment-node-id]       # add PRRC_... IDs
```

Output schema:

```json
{
  "reviews": [{
    "id": "PRR_...", "state": "CHANGES_REQUESTED",
    "author_login": "reviewer", "body": "...", "submitted_at": "...",
    "comments": [{
      "thread_id": "PRRT_...", "path": "src/file.py", "line": 42,
      "author_login": "reviewer", "body": "...", "created_at": "...",
      "is_resolved": false, "is_outdated": false,
      "thread_comments": [{ "author_login": "author", "body": "...", "created_at": "..." }]
    }]
  }]
}
```

### `review --submit` - Submit pending review

```bash
gh pr-review review --submit [NUMBER|URL] \
  -R owner/repo \
  --review-id PRR_... \
  --event APPROVE|COMMENT|REQUEST_CHANGES \   # default: COMMENT
  [--body "Summary"]     # required for REQUEST_CHANGES
# → { "status": "Review submitted successfully" }
```

### `comments reply` - Reply to a thread

```bash
gh pr-review comments reply [NUMBER|URL] \
  -R owner/repo \
  --thread-id PRRT_... \
  --body "reply" \
  [--review-id PRR_...]    # when replying within a pending review
# → { "comment_node_id": "PRRC_..." }
```

### `threads list` - Enumerate threads

```bash
gh pr-review threads list [NUMBER|URL] -R owner/repo [--unresolved] [--mine]
# → [{ "threadId": "R_...", "isResolved": false, "path": "...", "line": 42, ... }]
```

Note: `threadId` is `R_...` format here; `thread_id` in `review view` output is `PRRT_...`. Use `review view` to get IDs needed for `comments reply`.

### `threads resolve` / `threads unresolve`

```bash
gh pr-review threads resolve [NUMBER|URL] -R owner/repo --thread-id PRRT_...
gh pr-review threads unresolve [NUMBER|URL] -R owner/repo --thread-id PRRT_...
# → { "thread_node_id": "R_...", "is_resolved": true }
```

### End-to-end workflows

```bash
# Read and reply to unresolved comments
REVIEWS=$(gh pr-review review view -R owner/repo --pr 42 --unresolved --not_outdated)
echo "$REVIEWS" | jq -r '.reviews[].comments[].thread_id'   # collect PRRT_... IDs
gh pr-review comments reply 42 -R owner/repo \
  --thread-id PRRT_kwDOAAABbcdEFG12 --body "Fixed in abc123"
gh pr-review threads resolve 42 -R owner/repo --thread-id PRRT_kwDOAAABbcdEFG12

# Create review with inline comments
REVIEW_ID=$(gh pr-review review --start -R owner/repo 42 | jq -r .id)
gh pr-review review --add-comment 42 -R owner/repo \
  --review-id "$REVIEW_ID" --path src/main.py --line 15 --body "nit: rename"
gh pr-review review --submit 42 -R owner/repo \
  --review-id "$REVIEW_ID" --event REQUEST_CHANGES --body "See inline comments"

# Get current branch PR, view unresolved
PR=$(gh pr view --json number --jq .number)
gh pr-review review view -R owner/repo --pr "$PR" --unresolved --not_outdated --tail 1
```
