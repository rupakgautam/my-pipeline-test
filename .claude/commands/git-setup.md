# Claude Code Skill: /git-setup
# File: .claude/commands/git-setup.md
# Usage: /git-setup
#
# WHAT THIS SKILL DOES:
# Runs once on any new project. Creates .gitignore, .env.example,
# initializes git, creates dev branch, and walks you through GitHub setup.
# Replaces everything we did manually in the GitHub section.

You are a senior DevOps engineer. When I run /git-setup, do ALL of this automatically:

STEP 1 — Create .gitignore
Create a .gitignore file with these exact contents:
```
# Python
venv/
__pycache__/
*.pyc
*.pyo
.pytest_cache/

# Database — never commit real data
db/
*.db
*.sqlite3

# Secrets — NEVER commit these
.env
.env.*
!.env.example

# Pipeline output — generated files
data/cleaned/
data/validated/
data/invalid/
logs/

# OS
.DS_Store
.vscode/settings.json
```

STEP 2 — Create .env.example
Create .env.example with empty placeholders:
```
DATABASE_URL=
API_HOST=
API_PORT=
ENV=
SECRET_KEY=
API_KEYS=
```

STEP 3 — Initialize git
Run: git init
Run: git add .
Run: git status

STEP 4 — SAFETY CHECK (most important step)
Read the output of git status carefully.
If you see ANY of these files listed, STOP immediately and warn the user:
- .env
- db/
- db/pipeline.db
- data/cleaned/
- data/validated/
- logs/

If those files ARE present, do NOT commit. Tell the user exactly which file is exposed and how to fix .gitignore.

STEP 5 — First commit (only if safety check passed)
Run: git commit -m "initial project setup: pipeline, api, skills, security"

STEP 6 — Create dev branch
Run: git checkout -b dev

STEP 7 — Tell the user exactly what to do next
Print these exact instructions:
```
✅ Git initialized successfully!

Now do these steps manually (takes 2 minutes):

1. Go to https://github.com/new
2. Create a NEW repository:
   - Name: [use current folder name]
   - Visibility: Private (or Public)
   - Do NOT add README, .gitignore, or license

3. Get a Personal Access Token:
   Go to: https://github.com/settings/tokens/new
   Check: ✅ repo  ✅ workflow
   Copy the token (shown only once)

4. Run this command (replace YOUR_USERNAME and YOUR_TOKEN):
   git remote add origin https://YOUR_USERNAME:YOUR_TOKEN@github.com/YOUR_USERNAME/[repo-name].git
   git push -u origin main
   git push -u origin dev

5. Then run /git-cicd to set up GitHub Actions
```

Do not skip any step. Do not ask questions. Do everything automatically except the GitHub website steps which require a browser.
