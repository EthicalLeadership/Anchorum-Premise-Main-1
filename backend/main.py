"""
Anchorum-prem Backend API

FastAPI application that exposes the dossier_pipeline functionality as HTTP routes.

Routes:
- /evidence/{id}/summarize (Wire 7) - Saul Narrative summarization
- /cases/{id}/intake/email (Wire 8) - Email intake pipeline
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Import routes
from .routes.evidence import router as evidence_router
from .routes.cases import router as cases_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    print("Anchorum-prem backend starting...")
    
    yield
    
    # Shutdown
    print("Anchorum-prem backend shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    
    app = FastAPI(
        title="Anchorum-prem Backend API",
        description="Legal and audit toolkit API for dossier processing, contract review, classification, and enforcement.",
        version="1.0.0",
        lifespan=lifespan,
    )
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, restrict to specific origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(evidence_router, prefix="/api")
    app.include_router(cases_router, prefix="/api")
    
    # Health check endpoint
    @app.get("/health")
    async def health_check() -> dict:
        """Health check endpoint."""
        return {
            "status": "healthy",
            "service": "anchorum-prem-backend",
            "version": "1.0.0"
        }
    
    # Root endpoint with API documentation
    @app.get("/", response_class=HTMLResponse)
    async def root() -> str:
        """Root endpoint with API documentation link."""
        return """<!DOCTYPE html>
<html>
<head>
    <title>Anchorum-prem Backend</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
        h1 { color: #2c3e50; }
        .api-docs { background: #f8f9fa; padding: 20px; border-radius: 8px; margin-top: 20px; }
        a { color: #3498db; }
    </style>
</head>
<body>
    <h1>Anchorum-prem Backend API</h1>
    <p>Welcome to the Anchorum-prem backend service.</p>
    <div class="api-docs">
        <h2>Available Endpoints:</h2>
        <ul>
            <li><a href="/api/docs">Swagger UI (API Documentation)</a></li>
            <li><a href="/health">Health Check</a></li>
        </ul>
        <h2>Wire 7 - Evidence Summarization:</h2>
        <p>POST /api/evidence/{id}/summarize - Generate narrative summary using Saul AI</p>
        <h2>Wire 8 - Email Intake:</h2>
        <p>POST /api/cases/{id}/intake/email - Process .eml files through intake pipeline</p>
    </div>
</body>
</html>"""
    
    return app


# Create the app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    # Run with uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
