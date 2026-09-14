import time
from dotenv import load_dotenv
from langchain.agents import create_agent
from tools.tools import get_clima
from langchain.chat_models import init_chat_model

load_dotenv()

system_prompt=(
        "Você é um agente de turismo. Dado um estado sugira 3 cidades candidatas significativas no seu estado com atrações turísticas. "
        "Você DEVE OBRIGATORIAMENTE usar a ferramenta get_clima para checar o clima de cada uma ANTES de dar a resposta final. "
        "Se ao invés de um estado o usuário escrever uma cidade, você deve apenas checar o clima da cidade informada. "
        "Se o usuário escrever uma cidade sem o estado, você obrigatoriamente deve escrever ao final do texto a seguinte mensagem: 'OBS: Por favor, informe o estado (<nome_do_estado>) para que eu possa sugerir passeios em outras cidades do mesmo estado.' Você deve escrever o estado correspondente à cidade informada no campo <nome_do_estado>. "
        "Por favor, forneça a resposta em português e não inclua informações de clima para cidades fora do estado informado. "
        "Em seguida, pense em 3 passeios para cada cidade candidata, considerando o clima atual. "
        "Explique o porquê de cada recomendação citando o dado de clima (temperatura X, condição Y → passeio Z). "
        "A saída da resposta deve ser sempre: Cidade → Clima atual → O melhor dentre os 3 passeios para o clima atual → justificativa. Responda apenas isso e mais nada. "
        "Pense que climas extremos (muito frio, muito calor, chuva) podem impactar negativamente a experiência do passeio e que certos passeios ficam impedidos de serem realizados em determinadas condições climáticas. Portanto, considere o clima ao sugerir passeios e explique como o clima influencia a experiência do passeio."
    ),

model1 = init_chat_model(
    "groq:openai/gpt-oss-120b",
    temperature=0,
)
# 1. Agente Principal (Groq) - O mesmo que você já usava
agent_groq = create_agent(
    model=model1,
    tools=[get_clima],
    system_prompt=str(system_prompt),
)

model2 = init_chat_model(
    "google_genai:gemini-3.6-flash",
)
# 2. Agente Secundário (Gemini) - Para comparação
agent_gemini = create_agent(
    model=model2,
    tools=[get_clima],
    system_prompt=str(system_prompt),
)

def testar_modelo(nome, agente, estado):
    print(f"\n--- Testando {nome} ---")
    start = time.time()
    try:
        # A chamada invoke agora envia o input direto como no seu agent.py original
        resultado = agente.invoke({
            "messages": [{"role": "user", "content": f"Eu moro no {estado}"}]
        })
        tempo = time.time() - start
        
        print(f"Tempo de resposta: {tempo:.2f}s")
        # Pega a última mensagem da lista, que é a resposta do modelo
        resposta_bruta = resultado["messages"][-1].content
        # Se o modelo devolver uma lista de blocos (caso do Gemini)
        if isinstance(resposta_bruta, list):
            # Extrai apenas a string de dentro do dicionário de texto
            texto_limpo = resposta_bruta[0].get("text", str(resposta_bruta))
            print("Resposta:\n", texto_limpo)
        else:
            # Se for string simples (caso do Groq)
            print("Resposta:\n", resposta_bruta)
        
    except Exception as e:
        print(f"Erro no {nome}: {e}")

if __name__ == "__main__":
    estado = "Maranhão"
    testar_modelo("Groq", agent_groq, estado)
    testar_modelo("Gemini", agent_gemini, estado)