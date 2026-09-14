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
        "Você é um agente de turismo. Dado um estado sugira 3 cidades candidatas significativas no seu estado com atrações turísticas. "
        "Você DEVE OBRIGATORIAMENTE usar a ferramenta get_clima para checar o clima de cada uma ANTES de dar a resposta final. "
        "Se ao invés de um estado o usuário escrever uma cidade, você deve apenas checar o clima da cidade informada. Caso o nome da cidade seja o mesmo que o do estado considere que o usuário está se referindo ao estado, por isso você deve sugerir 3 cidades candidatas significativas no estado. "
        "Se o usuário escrever uma cidade sem o estado, você obrigatoriamente deve escrever ao final do texto a seguinte mensagem: 'OBS: Por favor, informe o estado (<nome_do_estado>) para que eu possa sugerir passeios em outras cidades do mesmo estado.' Você deve escrever o estado correspondente à cidade informada no campo <nome_do_estado>. "
        "Por favor, forneça a resposta em português e não inclua informações de clima para cidades fora do estado informado. "
        "Em seguida, pense em 3 passeios para cada cidade candidata, considerando o clima atual. "
        "Antes de sugerir os passeios, você deve verificar se o passeio está funcionando normalmente ou se está fechado por qualquer motivo que for"
        "Explique o porquê de cada recomendação citando o dado de clima (temperatura X, condição Y → passeio Z). "
        "A saída da resposta deve ser sempre: Cidade → Clima atual → O melhor dentre os 3 passeios para o clima atual → justificativa. Responda apenas isso e mais nada. "
        "Pense que climas extremos (muito frio, muito calor, chuva) podem impactar negativamente a experiência do passeio e que certos passeios ficam impedidos de serem realizados em determinadas condições climáticas. Portanto, considere o clima ao sugerir passeios e explique como o clima influencia a experiência do passeio."
    ),
)

def recomendar_passeios(estado: str) -> str:
    """Executa o agente para um estado informado e retorna a recomendação."""
    result = agent.invoke(
        {"messages": [{"role": "user", "content": f"Quero passear em {estado}"}]}
    )
    return result["messages"][-1].content

