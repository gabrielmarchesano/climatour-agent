from langchain.tools import tool
from datetime import datetime

from clients.geocode import get_cordinates
from clients.weather import get_weather_data, get_forecast_data
from clients.attractions import get_attractions
from tools.tempo import (
    agora_no_fuso,
    dia_semana_pt,
    fuso_por_offset_segundos,
    rotulo_offset,
)

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


def _previsao_com_fuso(lat: float, lon: float) -> dict:
    """
    Busca a previsão e guarda o fuso horário que ela já traz.

    A resposta do endpoint de previsão inclui ``city.timezone`` ("Shift in
    seconds from UTC"). Antes esse campo era descartado, e ``buscar_atracoes``
    fazia uma requisição de clima só para obter o mesmo dado. Isso pesava
    justamente nas conversas sobre viagem FUTURA, em que o agente chama
    get_previsao e não get_clima.
    """
    dados = get_forecast_data(lat, lon)
    offset = (dados.get("city") or {}).get("timezone")
    if offset is not None:
        _CACHE_TIMEZONE[_chave_coord(lat, lon)] = offset
    return dados


def _obter_fuso(lat: float, lon: float) -> int | None:
    """
    Devolve o deslocamento do fuso da coordenada, sem repetir requisições.

    Ordem de preferência:
      1. valor já guardado por get_clima OU get_previsao (custo zero);
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
    "Não há nada mapeado nem na cidade nem nos arredores dela. NÃO invente nomes "
    "de atrações. Informe que não encontrou atrações cadastradas na região, "
    "sugira consultar uma cidade maior por perto e use o clima ou a previsão "
    "para orientar o tipo de atividade."
)

# Quando a cidade pedida não tem nada mapeado, a busca é ampliada para os
# arredores. A resposta então NÃO pode afirmar que as atrações estão na cidade:
# ela precisa deixar claro que são sugestões próximas, no formato pedido.
_INSTRUCAO_ARREDORES = (
    "A cidade pedida não tem atrações mapeadas, mas as que estão em `atracoes` "
    "ficam PRÓXIMAS dela — veja `distancia_km` em cada uma. NÃO diga que elas "
    "estão dentro da cidade pedida e NÃO invente nada. "
    "Comece a resposta EXATAMENTE com esta frase, trocando x, y e z pelos nomes "
    "das atrações encontradas: "
    "\"Não encontramos atrações nesse local, mas próximo dessa cidade tem "
    "sugestões: x, y, z.\" "
    "Em seguida detalhe cada sugestão normalmente, dizendo a que distância fica "
    "e citando o clima ou a previsão para justificar a recomendação."
)

# Raios de busca, em metros, aplicados em ordem. O primeiro é a própria cidade;
# os seguintes só entram em cena se NADA for encontrado, para nunca devolver uma
# falha quando existe algo interessante por perto.
#
# Ampliar custa uma consulta extra no serviço de atrações, que tem limite por
# IP. Mas o custo só é pago justamente nos lugares onde a consulta é barata:
# se a cidade não tem nada mapeado, ela não é uma área densa.
RAIOS_BUSCA = (3000, 25000)

# Quantas janelas de 3h da previsão são enviadas ao modelo. 16 janelas = ~48h,
# cobrindo "hoje" e "amanhã" por inteiro em qualquer fuso e a qualquer hora do
# dia. Com as 8 antigas (~24h), uma pergunta sobre amanhã feita à noite recebia
# apenas as primeiras horas do dia seguinte.
JANELAS_PREVISAO = 16


def _resposta_degradada(cidade: str, status: str, motivo: str, instrucao: str) -> dict:
    """Monta o retorno da tool quando não há lista de atrações para entregar."""
    return {
        "status": status,
        "cidade": cidade,
        "motivo": motivo,
        "atracoes": [],
        "instrucao": instrucao,
    }


def _buscar_com_expansao(
    lat: float, lon: float, utc_offset: int | None
) -> tuple[list, int, bool]:
    """
    Procura atrações na cidade e, se não houver nenhuma, amplia para os arredores.

    Só a ausência de dados (``ValueError``) faz a busca expandir. Falhas de
    infraestrutura (timeout, rate limit, rede) sobem para quem chamou, porque
    ampliar o raio não resolveria — e só gastaria mais requisições.

    :return: (atrações, raio usado em metros, se veio dos arredores).
    :raise ValueError: quando nem o maior raio encontrou algo.
    """
    ultimo_vazio = None
    for indice, raio in enumerate(RAIOS_BUSCA):
        try:
            atracoes = get_attractions(
                lat, lon, raio=raio, utc_offset_seconds=utc_offset
            )
        except ValueError as e:
            # Nada mapeado neste raio: tenta o próximo, maior.
            ultimo_vazio = e
            continue
        return atracoes, raio, indice > 0

    raise ultimo_vazio or ValueError("Nenhuma atração encontrada na região.")


def _descrever_fuso_local(lat: float, lon: float) -> dict:
    """
    Descreve a hora local da cidade, para o modelo nunca ter que deduzi-la.

    Sem isso o modelo recebia apenas horários em UTC e chamava de "hoje" o dia
    UTC, o que erra o dia inteiro perto da meia-noite: às 22h20 em Brasília o
    UTC já está no dia seguinte.

    :return: dict com ``agora_local`` e ``fuso_utc``, ou dict vazio quando o
        fuso da cidade é desconhecido.
    """
    fuso = fuso_por_offset_segundos(_obter_fuso(lat, lon))
    if fuso is None:
        return {}
    agora = agora_no_fuso(fuso)
    return {
        "agora_local": agora.strftime("%Y-%m-%d %H:%M"),
        "dia_semana_local": dia_semana_pt(agora),
        "fuso_utc": rotulo_offset(agora),
    }


@tool
def get_clima(cidade: str, uf: str, country: str) -> dict:
    """
    Retorna as condições climáticas atuais de uma cidade que qualquer país que seja.
    Use esta ferramenta para saber se está chovendo, a temperatura
    e o clima geral de uma cidade específica dentro de um estado.

    Inclui `agora_local` e `fuso_utc`: a data e a hora NA CIDADE consultada.
    Use esses campos para falar do momento atual, nunca horários em UTC.
    """
    lat, lon = _coords(cidade, uf, country)
    clima = _clima_com_fuso(lat, lon)
    # Anota a hora local da cidade junto do payload bruto da API.
    clima.update(_descrever_fuso_local(lat, lon))
    return clima


@tool
def get_previsao(cidade: str, uf: str, country: str) -> dict:
    """
    Retorna a PREVISÃO do tempo dos próximos dias (não o clima atual) de uma cidade.
    Use quando o usuário perguntar sobre viajar/passear em uma data futura,
    fim de semana, amanhã, ou "os próximos dias".

    Cada item traz `data_hora_local` (data e hora NA CIDADE, formato
    YYYY-MM-DD HH:MM) e `dia_semana`. Use SEMPRE esses campos para casar a
    previsão com a data que o usuário pediu — eles já estão convertidos para o
    fuso da cidade, indicado em `fuso_utc`. A previsão cobre cerca de 5 dias;
    se a data pedida estiver fora desse alcance, diga isso em vez de estimar.
    """
    lat, lon = _coords(cidade, uf, country)
    # Guarda o fuso que vem na própria resposta, para buscar_atracoes reusar.
    previsao = _previsao_com_fuso(lat, lon)

    # A API devolve horários em UTC (`dt` epoch e `dt_txt`). Convertemos para a
    # hora local da cidade, que é a única que faz sentido para o usuário.
    fuso_cidade = fuso_por_offset_segundos(
        (previsao.get("city") or {}).get("timezone")
    )

    # Janelas de 3h cobrindo ~48h: o suficiente para responder "hoje" E
    # "amanhã" por inteiro, que é o caso mais comum de planejamento. Antes eram
    # 8 itens (~24h), que não cobriam o dia seguinte completo.
    itens = previsao.get("list", [])[:JANELAS_PREVISAO]
    resumo = []
    for item in itens:
        registro = {
            "temp": item.get("main", {}).get("temp"),
            "condicao": (item.get("weather") or [{}])[0].get("description"),
        }
        momento = _momento_local(item, fuso_cidade)
        if momento is not None:
            registro["data_hora_local"] = momento.strftime("%Y-%m-%d %H:%M")
            registro["dia_semana"] = dia_semana_pt(momento)
        else:
            # Fuso desconhecido: preserva o horário original, explicitamente
            # marcado como UTC, para o modelo não o confundir com hora local.
            registro["data_hora_utc"] = item.get("dt_txt")
        resumo.append(registro)

    resposta = {"cidade": cidade, "previsao": resumo}
    resposta.update(_descrever_fuso_local(lat, lon))
    return resposta


def _momento_local(item: dict, fuso_cidade) -> datetime | None:
    """
    Converte uma janela da previsão para a hora local da cidade.

    Usa o campo ``dt`` (epoch UTC), que é inequívoco, em vez de reinterpretar a
    string ``dt_txt``.

    :return: datetime na hora local, ou None se não for possível converter.
    """
    if fuso_cidade is None:
        return None
    epoch = item.get("dt")
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(int(epoch), tz=fuso_cidade)
    except (TypeError, ValueError, OSError):
        return None


@tool
def buscar_atracoes(cidade: str, uf: str, country: str) -> dict:
    """
    Busca atrações REAIS de uma cidade no OpenStreetMap: pontos turísticos,
    museus, restaurantes, cafés, bares, centros históricos, igrejas, praças,
    cachoeiras, praias, mirantes, parques e teatros.

    Se a cidade pedida não tiver nada mapeado, a busca é ampliada
    automaticamente para os arredores em vez de falhar.

    Retorna um objeto com o campo `status`:
      - "ok": `atracoes` traz a lista encontrada NA cidade.
      - "ok_arredores": a cidade não tem atrações mapeadas, e `atracoes` traz
        opções PRÓXIMAS a ela. Não afirme que ficam na cidade pedida.
      - "sem_dados": nada encontrado nem na cidade nem nos arredores.
      - "indisponivel": o serviço de atrações falhou (rate limit, timeout).

    Cada atração tem `nome`, `categoria`, o horário publicado (`horario`), se
    está aberta agora (`aberto`: True, False ou None quando desconhecido),
    `destaque` (verbete na Wikipédia) e `distancia_km` até a cidade consultada.

    O campo `instrucao` diz como responder em cada caso: siga-o e NUNCA invente
    atrações nem o status de aberto/fechado. Use esta ferramenta para descobrir
    passeios reais em vez de sugerir de memória.
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
        atracoes, raio_usado, dos_arredores = _buscar_com_expansao(
            lat, lon, utc_offset
        )
    except ValueError as e:
        # Ausência real de dados no OpenStreetMap, mesmo no raio ampliado.
        return _resposta_degradada(
            cidade, "sem_dados", str(e), _INSTRUCAO_SEM_DADOS
        )
    except Exception as e:
        # Timeout, rate limit, erro de rede ou resposta inválida do serviço.
        return _resposta_degradada(
            cidade, "indisponivel", f"{type(e).__name__}: {e}",
            _INSTRUCAO_INDISPONIVEL,
        )

    if dos_arredores:
        # A cidade em si não tinha nada: as atrações são da vizinhança, e a
        # resposta precisa deixar isso explícito.
        return {
            "status": "ok_arredores",
            "cidade": cidade,
            "raio_km": round(raio_usado / 1000),
            "atracoes": atracoes,
            "instrucao": _INSTRUCAO_ARREDORES,
        }

    return {"status": "ok", "cidade": cidade, "atracoes": atracoes}
