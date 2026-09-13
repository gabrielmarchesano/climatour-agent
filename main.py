from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from tools.agent import agent

app = FastAPI(title="Climatour Agent")


class RecomendacaoRequest(BaseModel):
    mensagem: str  # ex: "Quero passear em Minas Gerais"


class RecomendacaoResponse(BaseModel):
    recomendacao: str


@app.post("/recomendacao", response_model=RecomendacaoResponse)
def recomendar(request: RecomendacaoRequest):
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": request.mensagem}]}
        )
        resposta = result["messages"][-1].content
        return RecomendacaoResponse(recomendacao=resposta)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    return {"status": "ok"}