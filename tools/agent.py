from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from tools.tools import get_clima
from dotenv import load_dotenv

load_dotenv()

MODELOS_FALLBACK = [
    "groq:openai/gpt-oss-120b",
    "groq:openai/gpt-oss-20b", 
    "google_genai:gemini-3.6-flash",
    "groq:openai/gpt-oss-safeguard-20b",
    "groq:qwen/qwen3.6-27b"            
]

SYSTEM_PROMPT=(
        "Você é um agente de turismo. Dado um estado sugira 3 cidades candidatas significativas no seu estado com atrações turísticas. "
        "Você DEVE OBRIGATORIAMENTE usar a ferramenta get_clima para checar o clima de cada uma ANTES de dar a resposta final. "
        "Se ao invés de um estado o usuário escrever uma cidade, você deve apenas checar o clima da cidade informada. Caso o nome da cidade seja o mesmo que o do estado considere que o usuário está se referindo ao estado, por isso você deve sugerir 3 cidades candidatas significativas no estado. "
        "Se o usuário escrever uma cidade sem o estado, você obrigatoriamente deve escrever ao final do texto a seguinte mensagem: 'OBS: Por favor, informe o estado (<nome_do_estado>) para que eu possa sugerir passeios em outras cidades do mesmo estado.' Você deve escrever o estado correspondente à cidade informada no campo <nome_do_estado>. "
        "Por favor, forneça a resposta em português e não inclua informações de clima para cidades fora do estado informado. "
        "Em seguida, pense em 3 passeios para cada cidade candidata, considerando o clima atual. "
        "Antes de sugerir os passeios, você deve obrigatoriamente verificar se o passeio está funcionando ou se está fechado"
        "Explique o porquê de cada recomendação citando o dado de clima (temperatura X, condição Y → passeio Z). "
        "A saída da resposta deve ser sempre: Cidade → Clima atual → O melhor dentre os 3 passeios para o clima atual → justificativa. Responda apenas isso e mais nada. "
        "Pense que climas extremos (muito frio, muito calor, chuva) podem impactar negativamente a experiência do passeio e que certos passeios ficam impedidos de serem realizados em determinadas condições climáticas. Portanto, considere o clima ao sugerir passeios e explique como o clima influencia a experiência do passeio."
)


def recomendar_passeios(estado: str) -> str:
    """Tenta executar o agente alternando os modelos se o limite de requisições (429) for atingido."""
    
    for modelo_nome in MODELOS_FALLBACK:
        try:
            # Inicializa o modelo da vez
            model = init_chat_model(modelo_nome, temperature=0.1)
            
            # Cria o agente com o modelo atual
            agent = create_agent(
                model=model,
                tools=[get_clima],
                system_prompt=SYSTEM_PROMPT,
            )
            
            # Executa a busca
            result = agent.invoke(
                {"messages": [{"role": "user", "content": f"Quero passear em {estado}"}]}
            )
            conteudo = result["messages"][-1].content
            
            # Se vier como lista (com metadados/signature), extraímos apenas o texto
            if isinstance(conteudo, list):
                textos = [bloco["text"] for bloco in conteudo if isinstance(bloco, dict) and "text" in bloco]
                return "".join(textos)
            
            # Se já vier como texto puro
            return conteudo
            
        except Exception as e:
            erro_str = str(e).lower()
            # Se for erro 429 ou Rate Limit, ignora e tenta o próximo modelo do loop
            if "429" in erro_str or "rate limit" in erro_str:
                continue
            else:
                # Se for outro tipo de erro (ex: API key inválida), interrompe e mostra no Streamlit
                raise e
            
    return "Nossos servidores estão superlotados no momento! Atingimos o limite de consultas gratuitas na IA. Por favor, aguarde 1 minuto e tente buscar novamente."          

