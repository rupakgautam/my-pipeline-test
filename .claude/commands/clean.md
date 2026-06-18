You are a data cleaning expert. When I run /clean, do ALL of this automatically without asking me questions:
1. Read data/raw/sample_raw.json
2. Print what problems you find
3. Write pipeline/01_clean.py that fixes: duplicates (keep last by id), age coerced to int, dates normalized to YYYY-MM-DD, salary stripped of $ and commas converted to float, tags always a list, is_active always boolean, sensor_data missing keys filled with None
4. Run the script immediately
5. Write change log to logs/01_clean_log.json
6. Tell me: how many records in, duplicates removed, output location
