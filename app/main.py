import time
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from app.database import init_db
from app.seed_data import seed_database
from app.routers import (
    auth, donors, collections, inventory,
    requests, allocations, issues, reports,
    notifications, admin, demo
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables and seed demo data
    init_db()
    seed_database()
    yield

app = FastAPI(
    title="Blood Bank Management System (BBMS)",
    description="Software Engineering Laboratory Project - Compliant with Blood Bank Management System SRS v1.1",
    version="1.1.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Performance & Response Time Monitoring Middleware (BBMS-NF-001)
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = time.perf_counter() - start_time
    response.headers["X-Process-Time-Sec"] = f"{process_time:.4f}"
    return response

# Register Routers
app.include_router(auth.router)
app.include_router(donors.router)
app.include_router(collections.router)
app.include_router(inventory.router)
app.include_router(requests.router)
app.include_router(allocations.router)
app.include_router(issues.router)
app.include_router(reports.router)
app.include_router(notifications.router)
app.include_router(admin.router)
app.include_router(demo.router)

# Static Files
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
async def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return JSONResponse({"message": "Blood Bank Management System API is active. Visit /docs for Swagger UI."})

@app.get("/api/health", tags=["Health"])
def health_check():
    """Health check endpoint for availability monitoring (BBMS-NF-002)."""
    return {
        "status": "healthy",
        "system": "Blood Bank Management System",
        "version": "1.1.0",
        "compliance": "SRS v1.1 verified",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
