"""
Exceções próprias das APIs de DADOS (clima, geocodificação, atrações).

Por que isto existe
-------------------
O agente troca de modelo quando o Groq devolve 429: se o limite de um modelo
acabou, o próximo da fila atende. Essa decisão era tomada procurando "429" ou
"rate limit" no TEXTO do erro — e as APIs de dados usam exatamente as mesmas
palavras ("Limite de requisições excedido (Rate Limit)").

Resultado: um 429 da OpenWeatherMap ou da Overpass fazia o agente percorrer os
cinco modelos de LLM inutilmente, porque trocar de modelo não devolve cota de
uma API de clima. O usuário esperava cinco tentativas e recebia a mensagem
errada, dizendo que o limite era da IA.

Marcar a origem do erro com um tipo resolve isso na raiz: o laço de fallback
pergunta "este erro é do MODELO?" em vez de tentar adivinhar pelo texto.

Compatibilidade
---------------
Cada classe herda também do builtin que já era levantado antes, então quem
captura ``ConnectionError`` continua funcionando sem alteração.
"""


class ErroDeApiDeDados(Exception):
    """
    Marcador: a falha veio de uma API de dados, não do provedor de LLM.

    Serve para o laço de fallback de modelos descartar de imediato erros que
    trocar de modelo não resolveria.
    """


class LimiteDeRequisicoesDeDados(ErroDeApiDeDados, ConnectionError):
    """
    Uma API de dados recusou a requisição por limite de uso ou sobrecarga
    (HTTP 429 e, na Overpass, também 503/504).

    Herda de ``ConnectionError`` porque era esse o tipo levantado antes.
    """
