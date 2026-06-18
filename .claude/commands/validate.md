You are a data validation expert. When I run /validate, do ALL of this automatically without asking me questions:
1. Read data/cleaned/sample_clean.json
2. Write pipeline/02_validate.py using Pydantic v2 with these rules: id required, full_name required not null, age 0-120 if present, email must have @, salary positive if present, created valid YYYY-MM-DD if present
3. Run it immediately
4. Write passing records to data/validated/sample_valid.json
5. Write failing records with reasons to data/invalid/sample_invalid.json
6. Write summary to logs/02_validate_log.json
7. Tell me: how many passed, how many failed and why
