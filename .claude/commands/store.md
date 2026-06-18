You are a database engineer. When I run /store, do ALL of this automatically without asking me questions:
1. Read data/validated/sample_valid.json
2. Write pipeline/03_store.py that imports models/db_models.py, calls init_db(), upserts every record (insert if new id, update if exists), flattens sensor_data into columns, converts tags list to comma-separated string
3. Run it immediately
4. Write results to logs/03_store_log.json
5. Tell me: how many inserted, updated, failed, and the database file location
