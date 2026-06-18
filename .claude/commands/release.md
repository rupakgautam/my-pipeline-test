# Claude Code Skill: /release
# File: .claude/commands/release.md
# Usage: /release
#
# WHAT THIS SKILL DOES:
# Prepares and guides the dev → main release process.
# Checks everything is clean before going to production.
# Replaces the manual PR process for releases.

You are a senior release engineer. When I run /release, do ALL of this automatically:

STEP 1 — Check current state
Run: git status
If there are uncommitted changes, STOP and tell the user to commit or stash them first.

STEP 2 — Make sure local dev is up to date
Run: git checkout dev
Run: git pull origin dev
Show the user the last 5 commits on dev: git log --oneline -5

STEP 3 — Run the full pipeline to verify everything works
Run: python pipeline/01_clean.py
Run: python pipeline/02_validate.py
Run: python pipeline/03_store.py
If any step fails, STOP and tell the user what failed. Do not proceed with release.

STEP 4 — Test the API starts correctly
Start uvicorn in background, hit /health, then stop it.
If /health fails, STOP and tell the user.

STEP 5 — Show release summary
Print a summary of what will be released:
- List all commits in dev that are not in main: git log main..dev --oneline
- Show how many files changed: git diff main..dev --stat

STEP 6 — Guide the PR creation
Print:
```
✅ All checks passed! Ready to release to production.

Create the release PR on GitHub:
https://github.com/[detected from git remote]/compare/main...dev

PR Settings:
- Base: main
- Compare: dev  
- Title: release: deploy [date] — [summary of changes]
- Description: list the features/fixes included

After merging, GitHub Actions will run CI/CD automatically.
Monitor it at: https://github.com/[repo]/actions
```

IMPORTANT RULES:
- Never push directly to main
- Always run the pipeline before releasing
- If any test fails, do not release
- Release PRs go from dev → main only
