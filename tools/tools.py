from langchain.tools import tool
from clients.geocode import get_cordinates
from clients.weather import get_weather_data, get_forecast_data
from clients.attractions import get_attractions

# ---------------------------------------------------------------------------
# Memoização por processo.
#
# Numa única resposta o agente costuma chamar várias tools para a MESMA cidade
# (ex.: get_clima + buscar_atracoes, para 3 cidades candidatas). Sem cache:
#   - cada tool refazia o geocode da mesma cidade (1 round-trip HTTP extra);
#   - buscar_atracoes fazia uma SEGUNDA chamada de clima só para ler o campo
#     "timezone", mesmo quando get_clima já havia buscado o mesmo dado.
#
# Isso importa além do tempo: a API de atrações (Overpass) limita as consultas
# por IP, então toda requisição desperdiçada aproxima a aplicação do rate limit.
#
# Coordenadas de cidade não mudam, logo o cache de geocode não precisa de TTL.
# O fuso horário também é estável para uma coordenada.
# ---------------------------------------------------------------------------
_CACHE_COORDS: dict[tuple, tuple] = {}
_CACHE_TIMEZONE: dict[tuple, int] = {}


def _chave_local(cidade: str, uf: str, country: str) -> tuple:
    """Normaliza cidade/uf/país para servir de chave de cache."""
    return (
        (cidade or "").strip().lower(),
        (uf or "").strip().lower(),
        (country or "").strip().lower(),
    )


def _coords(cidade: str, uf: str, country: str) -> tuple:
    """Geocodifica a cidade reaproveitando o resultado já obtido na sessão."""
    chave = _chave_local(cidade, uf, country)
    if chave not in _CACHE_COORDS:
        _CACHE_COORDS[chave] = get_cordinates(cidade, uf, country)
    return _CACHE_COORDS[chave]


def _chave_coord(lat: float, lon: float) -> tuple:
    """Chave de cache por coordenada, arredondada para tolerar ruído."""
    return (round(float(lat), 3), round(float(lon), 3))


def _clima_com_fuso(lat: float, lon: float) -> dict:
    """
    Busca o clima atual e guarda o fuso horário da coordenada.

    O fuso fica disponível para ``buscar_atracoes``, que precisa dele para
    avaliar horários de funcionamento na hora local — evitando uma segunda
    chamada à API de clima.
    """
    dados = get_weather_data(lat, lon)
    offset = dados.get("timezone")
    if offset is not None:
        _CACHE_TIMEZONE[_chave_coord(lat, lon)] = offset
    return dados


def _obter_fuso(lat: float, lon: float) -> int | None:
    """
    Devolve o deslocamento do fuso da coordenada, sem repetir requisições.

    Ordem de preferência:
      1. valor já guardado por uma chamada anterior de get_clima (custo zero);
      2. uma consulta de clima, caso ainda não exista;
      3. None, se a consulta falhar — o status de funcionamento fica
         desconhecido, o que é preferível a ficar errado.
    """
    chave = _chave_coord(lat, lon)
    if chave in _CACHE_TIMEZONE:
        return _CACHE_TIMEZONE[chave]
    try:
        return _clima_com_fuso(lat, lon).get("timezone")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Degradação suave da busca de atrações.
#
# A API de atrações é um serviço público gratuito, sujeito a rate limit e
# sobrecarga. Antes, qualquer falha dela virava exceção e derrubava a
# recomendação INTEIRA — o usuário não recebia nem o clima, que já estava em
# mãos. Agora a tool devolve um objeto de status e o agente segue respondendo
# com o que tem, avisando o que não pôde ser confirmado.
#
# O campo "instrucao" descreve ao modelo o que fazer em cada caso, de modo que
# a regra de transparência (nunca inventar atração nem status de aberto)
# continue valendo mesmo quando os dados não chegam.
# ---------------------------------------------------------------------------
_INSTRUCAO_INDISPONIVEL = (
    "A consulta de atrações falhou por indisponibilidade do serviço. NÃO invente "
    "nomes de atrações. Diga ao usuário que a lista de atrações está "
    "temporariamente indisponível, faça a recomendação com base apenas no clima "
    "ou na previsão (ex.: sugerir tipo de atividade, como ao ar livre ou "
    "abrigada) e ofereça tentar novamente em alguns instantes."
)

_INSTRUCAO_SEM_DADOS = (
    "A consulta funcionou, mas não há atrações mapeadas para esta localidade. "
    "NÃO invente nomes de atrações. Informe que não encontrou atrações "
    "cadastradas nessa área, sugira uma cidade próxima maior e use o clima para "
    "orientar o tipo de atividade."
)


def _resposta_degradada(cidade: str, status: str, motivo: str, instrucao: str) -> dict:
    """Monta o retorno da tool quando não há lista de atrações para entregar."""
    return {
        "status": status,
        "cidade": cidade,
        "motivo": motivo,
        "atracoes": [],
        "instrucao": instrucao,
    }


@tool
def get_clima(cidade: str, uf: str, country: str) -> dict:
    """
    Retorna as condições climáticas atuais de uma cidade que qualquer país que seja.
    Use esta ferramenta para saber se está chovendo, a temperatura
    e o clima geral de uma cidade específica dentro de um estado.
    """
    lat, lon = _coords(cidade, uf, country)
    clima = _clima_com_fuso(lat, lon)
    return clima


@tool
def get_previsao(cidade: str, uf: str, country: str) -> dict:
    """
    Retorna a PREVISÃO do tempo dos próximos dias (não o clima atual) de uma cidade.
    Use quando o usuário perguntar sobre viajar/passear em uma data futura,
    fim de semana, amanhã, ou "os próximos dias".
    """
    lat, lon = _coords(cidade, uf, country)
    previsao = get_forecast_data(lat, lon)
    # Compacta para não estourar o contexto do modelo: janelas de 3h nas próximas ~24h
    itens = previsao.get("list", [])[:8]
    resumo = [
        {
            "data_hora": i.get("dt_txt"),
            "temp": i.get("main", {}).get("temp"),
            "condicao": (i.get("weather") or [{}])[0].get("description"),
        }
        for i in itens
    ]
    return {"cidade": cidade, "previsao": resumo}


@tool
def buscar_atracoes(cidade: str, uf: str, country: str) -> dict:
    """
    Busca atrações REAIS de uma cidade no OpenStreetMap: pontos turísticos,
    museus, restaurantes, cafés, bares, centros históricos, igrejas, praças,
    cachoeiras, praias, mirantes, parques e teatros.

    Retorna um objeto com o campo `status`:
      - "ok": `atracoes` traz a lista encontrada. Cada item tem `nome`,
        `categoria`, o horário publicado (`horario`), se está aberta agora
        (`aberto`: True, False ou None quando desconhecido) e `destaque`
        (atração com verbete na Wikipédia).
      - "indisponivel": o serviço de atrações falhou (rate limit, timeout).
      - "sem_dados": a consulta funcionou, mas nada há mapeado na área.

    Quando `status` não for "ok", a lista `atracoes` vem vazia e o campo
    `instrucao` diz como responder: siga-o e NUNCA invente atrações nem o
    status de aberto/fechado. Use esta ferramenta para descobrir passeios reais
    em vez de sugerir de memória.
    """
    try:
        lat, lon = _coords(cidade, uf, country)
    except Exception as e:
        # Sem coordenada não há busca possível; ainda assim não derrubamos a
        # conversa — o agente é orientado a seguir com o que tiver.
        return _resposta_degradada(
            cidade, "indisponivel",
            f"não foi possível localizar a cidade: {e}",
            _INSTRUCAO_INDISPONIVEL,
        )

    # O horário de funcionamento precisa ser avaliado na hora LOCAL da cidade.
    # Reaproveita o fuso já obtido por get_clima, quando houver.
    utc_offset = _obter_fuso(lat, lon)

    try:
        atracoes = get_attractions(lat, lon, utc_offset_seconds=utc_offset)
    except ValueError as e:
        # Ausência real de dados no OpenStreetMap: não é falha de infraestrutura.
        return _resposta_degradada(
            cidade, "sem_dados", str(e), _INSTRUCAO_SEM_DADOS
        )
    except Exception as e:
        # Timeout, rate limit, erro de rede ou resposta inválida do serviço.
        return _resposta_degradada(
            cidade, "indisponivel", f"{type(e).__name__}: {e}",
            _INSTRUCAO_INDISPONIVEL,
        )

    return {"status": "ok", "cidade": cidade, "atracoes": atracoes}
