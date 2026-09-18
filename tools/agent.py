from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from tools.tools import get_clima, get_previsao, buscar_atracoes
from dotenv import load_dotenv

load_dotenv()

MODELOS_FALLBACK = [
    "groq:openai/gpt-oss-120b",
    "groq:openai/gpt-oss-20b", 
    "google_genai:gemini-3.6-flash",
    "groq:openai/gpt-oss-safeguard-20b",
    "groq:qwen/qwen3.6-27b"            
]

SYSTEM_PROMPT = (
    "Você é o ClimaTour, um agente de turismo conversacional. Converse de forma "
    "natural e contínua, lembrando do que já foi dito no histórico da conversa.\n\n"

    "USO DAS FERRAMENTAS:\n"
    "- Use get_clima quando o usuário perguntar sobre o CLIMA ATUAL de uma cidade.\n"
    "- Use get_previsao quando o usuário falar em uma DATA FUTURA, amanhã, fim de "
    "semana ou 'os próximos dias' — planejamento futuro SEMPRE usa a previsão.\n"
    "- Use buscar_atracoes para descobrir ATRAÇÕES REAIS da cidade. Baseie as "
    "recomendações EXCLUSIVAMENTE no que essa ferramenta retornar. NÃO invente "
    "atrações de memória.\n\n"

    "STATUS DE FUNCIONAMENTO (regra de transparência):\n"
    "- Determine se uma atração está aberta/fechada SOMENTE pelo campo 'aberto' "
    "retornado por buscar_atracoes.\n"
    "- Se 'aberto' for True, informe que a atração está aberta.\n"
    "- Se 'aberto' for False, informe que a atração está fechada.\n"
    "- Se 'aberto' for None (desconhecido), escreva exatamente: "
    "'horário não confirmado, verifique antes de ir'.\n"
    "- NUNCA invente nem deduza o status de aberto/fechado quando ele não vier "
    "da ferramenta.\n\n"

    "JUSTIFICATIVA:\n"
    "- Ao recomendar um passeio, explique o porquê citando o dado de clima ou de "
    "previsão correspondente (temperatura, condição). Lembre que climas extremos "
    "(muito frio, muito calor, chuva) podem impedir ou prejudicar certos passeios.\n\n"

    "REFINAMENTO:\n"
    "- Considere o feedback do usuário (👍/👎 e mensagens de ajuste) para melhorar "
    "as próximas sugestões.\n\n"

    "Responda sempre em português, de forma clara e objetiva."
)


def formatar_status(aberto: bool | None) -> str:
    """
    Mapeia o campo Status_Aberto de uma atração para o rótulo de exibição,
    aplicando a regra de transparência do agente.

    Depende EXCLUSIVAMENTE do valor de `aberto`, sem considerar nenhum outro
    dado da atração (Requisitos 4.1, 4.2, 4.3, 4.4):
      - True  -> "aberta"
      - False -> "fechada"
      - None  -> "horário não confirmado, verifique antes de ir"

    :param aberto: valor do campo `aberto` retornado por `buscar_atracoes`.
    :return: rótulo de status correspondente.
    """
    if aberto is True:
        return "aberta"
    if aberto is False:
        return "fechada"
    return "horário não confirmado, verifique antes de ir"


def recomendar_passeios(
    historico: list[dict],
    feedback: dict[int, str] | None = None,
) -> str:
    """
    Gera a próxima resposta do agente a partir do histórico completo da
    conversa. Preserva o fallback de modelos por 429/rate limit.

    :param historico: lista de mensagens {"role": "user"|"assistant",
                      "content": str} em ordem cronológica.
    :param feedback: mapa opcional {indice_da_resposta: "positivo"|"negativo"}.
    :return: texto da resposta do agente.
    """
    # Monta o contexto (histórico + sinal de feedback) enviado ao modelo
    mensagens = _montar_mensagens(historico, feedback)

    for modelo_nome in MODELOS_FALLBACK:
        try:
            # Inicializa o modelo da vez
            model = init_chat_model(modelo_nome, temperature=0.1)
            
            # Cria o agente com o modelo atual
            agent = create_agent(
                model=model,
                tools=[get_clima, get_previsao, buscar_atracoes],
                system_prompt=SYSTEM_PROMPT,
            )
            
            # Executa a busca sobre o histórico completo da conversa
            result = agent.invoke({"messages": mensagens})
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
            
    return (
        "Nossos servidores estão superlotados no momento! Atingimos o limite "
        "de consultas gratuitas na IA. Por favor, aguarde 1 minuto e tente "
        "novamente."
    )


def _resumir_feedback(historico, feedback) -> str | None:
    """
    Descreve, em linguagem natural, quais respostas foram bem/mal avaliadas,
    para orientar o refinamento das próximas respostas.

    Retorna None quando não há feedback registrado.
    """
    if not feedback:
        return None
    positivas, negativas = [], []
    for indice, aval in feedback.items():
        trecho = historico[indice]["content"][:120] if 0 <= indice < len(historico) else ""
        (positivas if aval == "positivo" else negativas).append(trecho)
    partes = []
    if positivas:
        partes.append(
            "O usuário GOSTOU do estilo destas respostas anteriores; "
            "mantenha essa linha: " + " | ".join(positivas)
        )
    if negativas:
        partes.append(
            "O usuário NÃO gostou destas respostas anteriores; "
            "ajuste as próximas sugestões: " + " | ".join(negativas)
        )
    return "\n".join(partes) if partes else None


def _montar_mensagens(historico, feedback) -> list[dict]:
    """
    Converte o histórico da sessão em mensagens para o modelo e injeta o
    sinal de feedback avaliativo como contexto adicional.
    """
    mensagens = [
        {"role": m["role"], "content": m["content"]}
        for m in historico
    ]
    sinal = _resumir_feedback(historico, feedback)
    if sinal:
        # Sinal de feedback realimentado no contexto (Requisitos 5.3, 5.4)
        mensagens.append({"role": "user", "content": sinal})
    return mensagens
