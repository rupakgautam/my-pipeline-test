"""
SECURED FASTAPI — api/main.py
==============================
Implements everything from the API Deep Dive slides:

SLIDE 4 — Versioning    : all routes prefixed with /api/v1/
SLIDE 5 — AuthN/AuthZ   : API key proves WHO you are, roles control WHAT you can do
SLIDE 6 — API Keys      : stored in .env, never in code, sent via header
SLIDE 7 — JWT ready     : structure in place to swap API keys for JWT later
SLIDE 8 — Rate Limiting : max requests per time window, returns HTTP 429

HOW TO RUN:
    uvicorn api.main:app --reload

HOW TO TEST A SECURED ENDPOINT:
    # Without key — get 401
    curl http://localhost:8000/api/v1/users

    # With key — get data
    curl -H "X-API-Key: dev-key-12345" http://localhost:8000/api/v1/users

    # In browser docs — click Authorize button top right, enter your key
    http://localhost:8000/docs
"""

import sys
import time
import os
import secrets
from pathlib import Path
from typing import Optional
from datetime import datetime
from collections import defaultdict

from fastapi import FastAPI, Depends, HTTPException, Query, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent.parent))
from models.db_models import UserRecord as DBUser, PipelineRun as DBRun, get_db, init_db


# ── SLIDE 6: API Keys ─────────────────────────────────────────────────────────
#
# What it does: every request must include a key in the header.
# No key = 401 Unauthorized. Wrong key = 403 Forbidden.
# Keys live in .env — never hardcoded in source code.
#
# In production: store keys in a database so you can add/revoke them live.
# For now: loaded from .env for simplicity.

# Load valid API keys from .env
# Format in .env:  API_KEYS=key1,key2,key3
_raw_keys = os.getenv("API_KEYS", "dev-key-12345,readonly-key-99999")
VALID_API_KEYS: dict[str, str] = {}

# Each key maps to a role: admin or readonly
# In production this would come from a database
for i, key in enumerate(_raw_keys.split(",")):
    key = key.strip()
    if key:
        role = "admin" if i == 0 else "readonly"
        VALID_API_KEYS[key] = role

# Tell FastAPI to look for the key in a header called X-API-Key
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


# ── SLIDE 5: AuthN (Authentication) ──────────────────────────────────────────
#
# AuthN = WHO are you?
# This function checks the API key and returns who is making the request.
# Called as a dependency on every protected endpoint.

def authenticate(api_key: str = Security(API_KEY_HEADER)) -> dict:
    """
    AUTHN: Verifies the API key is valid.
    Returns the caller's identity (key + role).
    Raises 401 if no key provided, 403 if key is invalid.
    """
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="No API key provided. Add header: X-API-Key: your-key"
        )
    if api_key not in VALID_API_KEYS:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key."
        )
    return {"key": api_key, "role": VALID_API_KEYS[api_key]}


# ── SLIDE 5: AuthZ (Authorization) ───────────────────────────────────────────
#
# AuthZ = WHAT can you do?
# Being authenticated (valid key) doesn't mean you can do everything.
# Admin keys can write/delete. Readonly keys can only read.
#
# This is RBAC — Role Based Access Control (from the slide).

def require_admin(caller: dict = Depends(authenticate)) -> dict:
    """
    AUTHZ: Requires admin role.
    Use on POST, PUT, DELETE endpoints.
    Readonly keys get 403 here even though they have a valid API key.
    """
    if caller["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail="This action requires admin role. Your key is readonly."
        )
    return caller


# ── SLIDE 8: Rate Limiting ────────────────────────────────────────────────────
#
# What it does: limits how many requests one API key can make per minute.
# Too many = HTTP 429 Too Many Requests (exactly as shown in the slide).
#
# Algorithm used: Fixed Window (simplest, shown in slide).
# Each key gets a counter that resets every 60 seconds.
# Limit: 60 requests per minute per key (1 per second average).

class RateLimiter:
    """
    Fixed Window rate limiter.
    Stores request counts per API key in memory.
    In production: use Redis so limits work across multiple servers.
    """
    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.counters: dict[str, list] = defaultdict(list)

    def check(self, key: str) -> None:
        now = time.time()
        window_start = now - self.window_seconds

        # Remove timestamps outside the current window
        self.counters[key] = [t for t in self.counters[key] if t > window_start]

        # Check if over limit
        if len(self.counters[key]) >= self.max_requests:
            retry_after = int(self.counters[key][0] + self.window_seconds - now)
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)}  # slide shows this header
            )

        # Record this request
        self.counters[key].append(now)


# One global rate limiter instance shared across all requests
limiter = RateLimiter(max_requests=60, window_seconds=60)


def rate_limit(
    request: Request,
    caller: dict = Depends(authenticate)
) -> dict:
    """
    Dependency that applies rate limiting after authentication.
    Uses the API key as the rate limit identifier.
    Chain: authenticate → rate_limit → endpoint handler.
    """
    limiter.check(caller["key"])
    return caller


# ── SLIDE 4: API Versioning ───────────────────────────────────────────────────
#
# URI versioning: /api/v1/users — most common, clear in browser/logs.
# When you make breaking changes later, add /api/v2/ alongside v1.
# Never break existing clients — keep v1 alive until migration is done.

app = FastAPI(
    title="Data Pipeline API",
    version="1.0.0",
    description="""
    Secured REST API for the data engineering pipeline.

    **Authentication**: All endpoints require an API key in the `X-API-Key` header.
    Click the **Authorize** button above and enter your key to test here.

    **Roles**:
    - `admin` — full access (read + write + delete)
    - `readonly` — read-only access (GET endpoints only)

    **Rate limit**: 60 requests per minute per key.
    """,
    # Swagger UI authorize button
    openapi_tags=[
        {"name": "Health", "description": "Public — no auth required"},
        {"name": "Users", "description": "Requires API key"},
        {"name": "Pipeline", "description": "Requires admin key"},
    ]
)

# SLIDE 2 (Why APIs): CORS — lock this down to your frontend domain in production
# Right now: localhost only (not open to the world)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",   # React dev server
        "http://localhost:8080",   # Vue dev server
        "http://localhost:5173",   # Vite dev server
        # Add your production domain here when you deploy
        # "https://your-app.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class SensorOut(BaseModel):
    temperature: Optional[float] = None
    humidity:    Optional[float] = None
    pressure:    Optional[float] = None

class UserOut(BaseModel):
    id:          str
    full_name:   Optional[str] = None
    age:         Optional[int] = None
    email:       Optional[str] = None
    department:  Optional[str] = None
    salary:      Optional[float] = None
    created:     Optional[str] = None
    last_login:  Optional[str] = None
    is_active:   Optional[bool] = None
    tags:        list[str] = []
    sensor_data: SensorOut
    inserted_at: Optional[datetime] = None
    model_config = {"from_attributes": True}

class UserCreate(BaseModel):
    id:          str
    full_name:   str
    age:         Optional[int] = None
    email:       str
    department:  Optional[str] = None
    salary:      Optional[float] = None
    created:     Optional[str] = None
    is_active:   Optional[bool] = True
    tags:        list[str] = []
    temperature: Optional[float] = None
    humidity:    Optional[float] = None
    pressure:    Optional[float] = None

def to_out(u: DBUser) -> UserOut:
    return UserOut(
        id=u.id, full_name=u.full_name, age=u.age, email=u.email,
        department=u.department, salary=u.salary, created=u.created,
        last_login=u.last_login, is_active=u.is_active,
        tags=u.tags.split(",") if u.tags else [],
        sensor_data=SensorOut(temperature=u.temperature,
                              humidity=u.humidity, pressure=u.pressure),
        inserted_at=u.inserted_at
    )


# ── VERSIONED ROUTER (/api/v1/) ───────────────────────────────────────────────
# All routes below use /api/v1/ prefix — URI versioning from slide 4.

# ── PUBLIC endpoint — no auth ─────────────────────────────────────────────────
@app.get("/", tags=["Health"])
def root():
    """Welcome message at the API root."""
    return {"message": "Welcome to the Data Pipeline API", "docs": "/docs"}


@app.get("/health", tags=["Health"])
def health():
    """
    Public health check — no API key required.
    Use this to check if the server is up without needing credentials.
    """
    return {
        "status": "ok",
        "time": datetime.utcnow().isoformat(),
        "version": "v1"
    }
@app.get("/health", tags=["Health"])
def health():
    """
    Public health check — no API key required.
    Use this to check if the server is up without needing credentials.
    """
    return {
        "status": "ok",
        "time": datetime.utcnow().isoformat(),
        "version": "v1"
    }

@app.get("/api/v1/health", tags=["Health"])
def health_v1():
    """Versioned health check."""
    return {"status": "ok", "time": datetime.utcnow().isoformat(), "version": "v1"}


# ── SECURED endpoints — require API key + rate limit ─────────────────────────

@app.get("/api/v1/users", response_model=list[UserOut], tags=["Users"])
def list_users(
    db:         Session        = Depends(get_db),
    caller:     dict           = Depends(rate_limit),   # AuthN + rate limit
    limit:      int            = Query(20, ge=1, le=100, description="Slide 3: max 100"),
    offset:     int            = Query(0, ge=0,          description="Slide 3: pagination"),
    department: Optional[str]  = Query(None),
    is_active:  Optional[bool] = Query(None),
    min_salary: Optional[float]= Query(None),
    max_salary: Optional[float]= Query(None),
):
    """
    List users. Requires any valid API key (admin or readonly).
    Supports filtering and pagination (slide 3 — offset-based).
    """
    q = db.query(DBUser)
    if department:  q = q.filter(DBUser.department == department)
    if is_active is not None: q = q.filter(DBUser.is_active == is_active)
    if min_salary:  q = q.filter(DBUser.salary >= min_salary)
    if max_salary:  q = q.filter(DBUser.salary <= max_salary)
    return [to_out(r) for r in q.offset(offset).limit(limit).all()]


@app.get("/api/v1/users/stats/summary", tags=["Users"])
def stats(
    db:     Session = Depends(get_db),
    caller: dict    = Depends(rate_limit),
):
    """Statistics summary. Requires any valid API key."""
    all_u = db.query(DBUser).all()
    if not all_u:
        raise HTTPException(404, "No users yet")
    salaries = [u.salary for u in all_u if u.salary]
    ages     = [u.age    for u in all_u if u.age]
    depts: dict[str, int] = {}
    for u in all_u:
        d = u.department or "Unknown"
        depts[d] = depts.get(d, 0) + 1
    return {
        "total_users":  len(all_u),
        "active_users": sum(1 for u in all_u if u.is_active),
        "avg_salary":   round(sum(salaries)/len(salaries), 2) if salaries else None,
        "avg_age":      round(sum(ages)/len(ages), 1)         if ages     else None,
        "departments":  depts,
        "requested_by": caller["role"]   # shows who called it
    }


@app.get("/api/v1/users/active/summary", tags=["Users"])
def active_users_summary(
    db:     Session = Depends(get_db),
    caller: dict    = Depends(rate_limit),
):
    """
    Return only active users along with their average salary.
    Requires any valid API key. Defined before /users/{user_id} so the
    static path is not shadowed by the dynamic route.
    """
    active = db.query(DBUser).filter(DBUser.is_active == True).all()
    if not active:
        raise HTTPException(404, "No active users found")
    salaries = [u.salary for u in active if u.salary is not None]
    return {
        "active_user_count": len(active),
        "average_salary": round(sum(salaries) / len(salaries), 2) if salaries else None,
        "users": [to_out(u) for u in active],
        "requested_by": caller["role"],
    }


@app.get("/api/v1/users/{user_id}", response_model=UserOut, tags=["Users"])
def get_user(
    user_id: str,
    db:      Session = Depends(get_db),
    caller:  dict    = Depends(rate_limit),
):
    """Get one user by ID. Requires any valid API key."""
    u = db.query(DBUser).filter(DBUser.id == user_id).first()
    if not u:
        raise HTTPException(404, f"User {user_id} not found")
    return to_out(u)


# ── ADMIN-ONLY endpoints — require admin role ─────────────────────────────────

@app.post("/api/v1/users", response_model=UserOut, status_code=201, tags=["Users"])
def create_user(
    p:      UserCreate,
    db:     Session = Depends(get_db),
    caller: dict    = Depends(require_admin),   # AUTHZ: admin only
):
    """
    Create a new user. ADMIN ONLY.
    Readonly keys get 403 here even if they are valid.
    """
    if db.query(DBUser).filter(DBUser.id == p.id).first():
        raise HTTPException(409, f"User {p.id} already exists")
    u = DBUser(
        id=p.id, full_name=p.full_name, age=p.age, email=p.email,
        department=p.department, salary=p.salary, created=p.created,
        is_active=p.is_active, tags=",".join(p.tags) if p.tags else None,
        temperature=p.temperature, humidity=p.humidity, pressure=p.pressure,
        inserted_at=datetime.utcnow()
    )
    db.add(u); db.commit(); db.refresh(u)
    return to_out(u)


@app.delete("/api/v1/users/{user_id}", tags=["Users"])
def delete_user(
    user_id: str,
    db:      Session = Depends(get_db),
    caller:  dict    = Depends(require_admin),   # AUTHZ: admin only
):
    """Delete a user. ADMIN ONLY."""
    u = db.query(DBUser).filter(DBUser.id == user_id).first()
    if not u:
        raise HTTPException(404, f"User {user_id} not found")
    db.delete(u); db.commit()
    return {"message": f"User {user_id} deleted", "deleted_by": caller["role"]}


@app.get("/api/v1/pipeline/runs", tags=["Pipeline"])
def pipeline_runs(
    db:     Session = Depends(get_db),
    caller: dict    = Depends(require_admin),   # AUTHZ: admin only
):
    """Pipeline run history. ADMIN ONLY."""
    return db.query(DBRun).order_by(DBRun.run_at.desc()).all()
@app.get("/api/v1/users/department/{dept}", response_model=list[UserOut], tags=["Users"])
def users_by_department(
    dept:   str,
    db:     Session = Depends(get_db),
    caller: dict    = Depends(rate_limit),
):
    """
    Get all users in a specific department.
    Example: /api/v1/users/department/Engineering
    """
    users = db.query(DBUser).filter(DBUser.department == dept).all()
    if not users:
        raise HTTPException(404, f"No users found in department: {dept}")
    return [to_out(u) for u in users]