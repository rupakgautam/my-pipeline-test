# Claude Code Skill: /feature
# File: .claude/commands/feature.md
# Usage: /feature add salary filter to API
#
# WHAT THIS SKILL DOES:
# Replaces the entire manual workflow:
# - Creates feature branch from dev
# - Makes the code changes you describe
# - Commits with proper message
# - Pushes to GitHub
# - Gives you the exact PR link to open
#
# EXAMPLE USAGE:
# /feature add a GET endpoint that returns users by salary range
# /feature add rate limiting to the delete endpoint
# /feature fix the bug where tags are returned as null

You are a senior software engineer. When I run /feature [description], do ALL of this automatically:

The feature I want to build: $ARGUMENTS

STEP 1 — Start from dev (always)
Run: git checkout dev
Run: git pull origin dev
If this fails, tell the user to check their internet connection or GitHub token.

STEP 2 — Create a feature branch
Convert the description into a short branch name (lowercase, hyphens, no spaces, max 5 words).
Example: "add salary filter to API" → "feature/add-salary-filter"
Run: git checkout -b feature/[short-name]

STEP 3 — Make the code changes
Read the relevant files first to understand the current code.
Make ONLY the changes needed for this feature.
Do not refactor unrelated code.
Do not change files that are not needed for this feature.

STEP 4 — Verify the changes work
If the change is to api/main.py, check for syntax errors.
If the change is to a pipeline script, run it to verify.

STEP 5 — Stage only changed files
Run: git add [only the files you changed]
Run: git status to confirm what is staged
Never run: git add . (too broad, might catch temp files)

STEP 6 — Commit with conventional commit message
Format: type: short description
Types: feat (new feature), fix (bug fix), docs (documentation), refactor (code cleanup)
Example: git commit -m "feat: add GET /api/v1/users/salary-range endpoint"

STEP 7 — Push to GitHub
Run: git push origin feature/[branch-name]

STEP 8 — Give the user the PR link and instructions
Print:
```
✅ Feature branch pushed to GitHub!

Open this URL to create your Pull Request:
https://github.com/[detected from git remote]/pull/new/feature/[branch-name]

PR Settings:
- Base branch: dev (NOT main)
- Title: [your commit message]
- Description: explain what changed and how to test it

After merging feature → dev, run /release to merge dev → main
```

IMPORTANT RULES:
- Never commit .env or db/ files
- Never push directly to main or dev
- Always create a feature branch
- Commit message must start with: feat:, fix:, docs:, or refactor:
- If git status shows .env or db/, STOP and warn the user immediately
