import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from orchestrator.agent import SystemAgentOrchestrator

app = FastAPI(title="Multi Agent Server API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize single shared orchestrator instance (lazy-loads model on first request)
orchestrator = SystemAgentOrchestrator()

class QueryRequest(BaseModel):
    prompt: str

class ConfirmRequest(BaseModel):
    token: str
    action: str

@app.post("/api/query")
async def execute_query(req: QueryRequest):
    try:
        result = await orchestrator.execute_query(req.prompt)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "model": "Qwen3.5-4BQ"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)