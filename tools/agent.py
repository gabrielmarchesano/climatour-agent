from langchain.agents import create_agent
from tools.tools import get_clima
from dotenv import load_dotenv

load_dotenv()
agent = create_agent(
    model="groq:openai/gpt-oss-120b",
    tools=[get_clima],
    temperature=0,
    system_prompt=(
        "Você é um agente de turismo. Dado um estado brasileiro, "
        "sugira cidades candidatas com atrações turísticas, use a "
        "ferramenta get_clima para checar o clima de cada "
        "uma. explique o porquê de cada recomendação citando o dado de clima (temperatura X, condição Y → passeio Z)." \
        "Por favor, forneça a resposta em português e não inclua informações de clima para cidades fora do estado informado."
        "A saída da resposta deve ser sempre: Cidade → Clima atual → 3 passeios → justificativa"
        "Pense que climas extremos (muito frio, muito calor, chuva) podem impactar negativamente a experiência do passeio e que certos passeios ficam impedidos de serem realizados em determinadas condições climáticas. Portanto, considere o clima ao sugerir passeios e explique como o clima influencia a experiência do passeio."
    ),
)

def recomendar_passeios(estado: str) -> str:
    """Executa o agente para um estado brasileiro informado e retorna a recomendação."""
    result = agent.invoke(
        {"messages": [{"role": "user", "content": f"Quero passear em {estado}"}]}
    )
    return result["messages"][-1].content

