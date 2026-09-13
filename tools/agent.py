from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from tools.tools import get_clima
from dotenv import load_dotenv

load_dotenv()

model = init_chat_model(
    "groq:openai/gpt-oss-120b",
    temperature=0.1,
)

agent = create_agent(
    model=model,
    tools=[get_clima],
    system_prompt=(
        "Você é um agente de turismo. Dado um estado brasileiro, "
        "sugira cidades candidatas significativas nesse estado com atrações turísticas, use a "
        "ferramenta get_clima para checar o clima de cada "
        "uma. Explique o porquê de cada recomendação citando o dado de clima (temperatura X, condição Y → passeio Z)." \
        "Por favor, forneça a resposta em português e não inclua informações de clima para cidades fora do estado informado."
        "Em seguida, pense em 3 passeios para cada cidade candidata, considerando o clima atual. "
        "A saída da resposta deve ser sempre: Cidade → Clima atual → O melhor entre os 3 passeios → justificativa. Responda apenas isso e mais nada"
        "Pense que climas extremos (muito frio, muito calor, chuva) podem impactar negativamente a experiência do passeio e que certos passeios ficam impedidos de serem realizados em determinadas condições climáticas. Portanto, considere o clima ao sugerir passeios e explique como o clima influencia a experiência do passeio."
    ),
)

def recomendar_passeios(estado: str) -> str:
    """Executa o agente para um estado brasileiro informado e retorna a recomendação."""
    result = agent.invoke(
        {"messages": [{"role": "user", "content": f"Quero passear em {estado}"}]}
    )
    return result["messages"][-1].content

