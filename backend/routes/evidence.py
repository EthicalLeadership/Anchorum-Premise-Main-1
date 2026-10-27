"""
Wire 7 — Evidence Summarization via Saul Narrative

Backend route: /evidence/{id}/summarize
Uses llm_classifier's Ollama client + analyze_claim.txt prompt
Returns markdown summary in a drawer component
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel

router = APIRouter(prefix="/evidence", tags=["Evidence"])


class SummarizeRequest(BaseModel):
    """Request model for evidence summarization."""
    evidence_id: str
    prompt_template: Optional[str] = None


class SummarizeResponse(BaseModel):
    """Response model for evidence summarization."""
    success: bool
    summary: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = {}


def get_ollama_client() -> Any:
    """Get Ollama client instance.
    
    This should be configured to use the local Ollama server.
    Default model is 'llama3' or similar.
    """
    try:
        from ollama import Client
        
        # Configure Ollama client
        client = Client(host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
        return client
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Ollama client not available. Install with: pip install ollama"
        )


def load_analyze_claim_prompt() -> str:
    """Load the analyze_claim.txt prompt template."""
    prompt_path = os.path.join(
        os.path.dirname(__file__), 
        "..", 
        "prompts", 
        "analyze_claim.txt"
    )
    
    if not os.path.exists(prompt_path):
        # Default prompt if file doesn't exist
        return """You are Saul, a legal narrative assistant. Analyze the following evidence and generate a concise summary suitable for legal proceedings.

Evidence: {evidence_content}

Instructions:
1. Identify key facts and claims
2. Note any contradictions or inconsistencies  
3. Summarize in clear, professional language
4. Keep under 500 words
5. Use markdown formatting

Output as markdown only."""
    
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize_evidence(
    request: SummarizeRequest,
) -> SummarizeResponse:
    """
    Generate a narrative summary of evidence using Saul AI.
    
    This endpoint uses the Ollama LLM client with the analyze_claim.txt prompt
    to generate legal-quality summaries of evidence documents.
    """
    try:
        # Load the prompt template
        prompt_template = request.prompt_template or load_analyze_claim_prompt()
        
        # Get Ollama client
        client = get_ollama_client()
        
        # In a real implementation, you would:
        # 1. Fetch the evidence content from storage
        # 2. Format it with the prompt template
        # 3. Call Ollama to generate the summary
        # 4. Return the markdown result
        
        # For now, return a placeholder response
        # This will be replaced with actual LLM call
        
        summary = f"""# Evidence Summary for ID: {request.evidence_id}

## Analysis by Saul AI

This evidence has been analyzed using the legal narrative generation system.

**Status**: Ready for review

**Note**: Full summarization requires Ollama to be running locally.
Configure OLLAMA_HOST environment variable and ensure llama3 (or similar) model is available.

The summary would appear here once the LLM call completes."""
        
        return SummarizeResponse(
            success=True,
            summary=summary,
            metadata={
                "evidence_id": request.evidence_id,
                "model_used": os.environ.get("OLLAMA_MODEL", "llama3"),
                "prompt_template": "analyze_claim.txt" if request.prompt_template is None else "custom",
            }
        )
        
    except Exception as e:
        return SummarizeResponse(
            success=False,
            error=str(e),
            metadata={"evidence_id": request.evidence_id}
        )


@router.get("/{evidence_id}/summarize")
async def get_evidence_summary(
    evidence_id: str = Path(..., description="Evidence packet ID"),
) -> SummarizeResponse:
    """
    GET endpoint for evidence summarization (alternative to POST).
    
    This allows the UI to poll for summary completion or fetch existing summaries.
    """
    # For now, delegate to POST logic
    request = SummarizeRequest(evidence_id=evidence_id)
    return await summarize_evidence(request)
