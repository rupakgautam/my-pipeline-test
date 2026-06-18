# Claude Code Skill: /git-cicd
# File: .claude/commands/git-cicd.md
# Usage: /git-cicd
#
# WHAT THIS SKILL DOES:
# Creates the complete GitHub Actions CI/CD pipeline file.
# Automatically tests your pipeline and API on every push.
# Replaces manually creating .github/workflows/pipeline.yml

You are a senior DevOps engineer. When I run /git-cicd, do ALL of this automatically:

STEP 1 — Create the workflows directory
Run: mkdir -p .github/workflows

STEP 2 — Create .github/workflows/pipeline.yml
Create this exact file:

```yaml
name: CI/CD Pipeline

on:
  push:
    branches: [main, dev]
  pull_request:
    branches: [main, dev]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run pipeline
        run: |
          python pipeline/01_clean.py
          python pipeline/02_validate.py
          python pipeline/03_store.py
        env:
          DATABASE_URL: sqlite:///db/pipeline.db

      - name: Test API starts and responds
        run: |
          uvicorn api.main:app &
          sleep 3
          curl -f http://localhost:8000/health
        env:
          API_KEYS: test-key-12345
          DATABASE_URL: sqlite:///db/pipeline.db

  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - name: Deploy to production
        run: echo "Add your deploy command here when ready"
```

STEP 3 — Commit and push the workflow
Run: git add .github/
Run: git commit -m "ci: add GitHub Actions CI/CD pipeline"
Run: git push origin dev

STEP 4 — Tell the user what happens next
Print:
```
✅ GitHub Actions CI/CD pipeline created!

Every time you push to dev or main:
- GitHub spins up Ubuntu server
- Installs Python + packages
- Runs your full pipeline (clean → validate → store)
- Starts FastAPI and hits /health
- Reports pass or fail

Monitor runs at:
https://github.com/[repo]/actions

Next steps:
1. Add secrets: GitHub repo → Settings → Secrets → Actions
   Add: DATABASE_URL, SECRET_KEY, API_KEYS
2. When ready to deploy, update the deploy job with your server command
```

Do not skip any step. Do everything automatically.
