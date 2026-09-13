from langchain.agents import create_agent
from tools.tools import get_clima
from dotenv import load_dotenv

load_dotenv()
agent = create_agent(
    model="groq:openai/gpt-oss-120b",
    tools=[get_clima],
    system_prompt=(
        "Você é um agente de turismo. Dado um estado brasileiro, "
        "sugira cidades candidatas com atrações turísticas, use a "
        "ferramenta get_clima para checar o clima de cada "
        "uma, e recomende 3 passeios com base na regra: chuva → indoor, "
        "calor+sol → natureza/cachoeira, frio → centro histórico."
    ),
)

result = agent.invoke(
    {"messages": [{"role": "user", "content": "Quero passear em Minas Gerais"}]}
)
print(result["messages"][-1].content)