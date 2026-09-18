
"""
Cliente de atrações turísticas baseado na Overpass API (OpenStreetMap).

Substitui a OpenTripMap (fora do ar). Vantagens:
  - Gratuita e SEM chave de API;
  - Cobertura mundial, incluindo todo o Brasil (é a própria base do OSM);
  - Expõe a tag ``opening_hours``, que permite dizer se a atração está aberta.

Abrangência: qualquer tipo de atração entra — pontos turísticos clássicos,
restaurantes, cafés, bares, centros históricos, igrejas, praças, cachoeiras,
praias, mirantes, parques, teatros e mercados.

IMPORTANTE sobre horários: no Brasil apenas ~12% dos POIs têm ``opening_hours``
preenchido (medido em BH: 32 de 258 restaurantes). Portanto ``aberto`` será None
com frequência. Isso é intencional e honesto: a avaliação é conservadora e só
retorna True/False quando a expressão é compreendida com segurança, para que o
agente nunca invente o status.

O OSM não possui avaliações nem popularidade, então "restaurante famoso" não
existe como dado. A relevância é aproximada por sinais reais (verbete na
Wikipédia/Wikidata, horário e site publicados) — ver ``_pontuar``.

NÃO EXISTE CHAVE DE API AQUI. A Overpass é anônima: não há ``api_key``, token
nem sessão que possa expirar. O único requisito da política de uso do OSM é
enviar um ``User-Agent`` que identifique a aplicação (ver ``HEADERS``). Quando
aparece "a requisição para a API de atrações expirou", é TIMEOUT de consulta ou
de rede, nunca problema de credencial.

Causas do erro que este módulo passou a tratar, todas medidas na prática:

1. Espelho morto. ``overpass.kumi.systems`` saiu da lista de instâncias
   públicas do OSM e hoje aceita a conexão mas não responde (travou por mais de
   160s numa consulta trivial). Era o único espelho alternativo, então qualquer
   falha do servidor principal virava timeout. Substituído por instâncias
   ativas e documentadas no wiki do OSM.

2. Orçamento de execução menor que o custo da consulta — a causa raiz. A query
   declarava ``[timeout:25]``, mas as 8 buscas num centro urbano denso custam
   mais que isso. Medição em Belo Horizonte no servidor principal: HTTP 200 em
   33,3s com ``elements`` VAZIO. A Overpass não devolve erro HTTP nesse caso;
   devolve 200 com um campo ``remark`` dizendo que abortou a consulta. O código
   antigo ignorava ``remark``, lia zero atrações e falhava. Agora o orçamento é
   maior, o timeout do cliente é sempre MAIOR que o do servidor, e ``remark``
   é detectado e tratado como falha.

3. Consulta caro demais por construção. ``around:`` obriga o servidor a calcular
   distância para cada candidato. Passou a usar caixa delimitadora (bbox), bem
   mais barata, com o raio exato aplicado no cliente via Haversine: mesma
   semântica de "raio em metros", muito menos trabalho no servidor.

4. Sem teto de tempo nem cache. Agora há prazo total para toda a operação e
   cache em memória por coordenada (a política do OSM pede cache e moderação).
"""

import math
import re
import time
import requests
from datetime import datetime, timedelta, timezone

# Espelhos públicos da Overpass API, tentados em ordem. Todos anônimos (sem
# chave), conferidos no wiki oficial do OSM ("Public Overpass API instances")
# e testados deste projeto.
#
# Descartados, com o motivo medido:
#   - ``overpass.kumi.systems``: saiu do wiki; aceita a conexão e nunca
#     responde (travou >160s numa consulta trivial). Era o antigo 2º espelho.
#   - ``overpass-api.openstreetmap.fr``: o DNS não resolve.
#   - ``overpass.osm.jp``: falha no handshake TLS (SSLError por certificado).
OVERPASS_ENDPOINTS = (
    # Instância principal (FOSSGIS). A única que já devolveu dados em todos os
    # testes, porém reconhecidamente sobrecarregada — daí os espelhos abaixo.
    "https://overpass-api.de/api/interpreter",
    # Private.coffee — 4 servidores de 20 núcleos e 256 GB.
    "https://overpass.private.coffee/api/interpreter",
    # VK Maps — declara não aplicar limite de requisições.
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)

# A política de uso do OSM exige identificar a aplicação.
HEADERS = {"User-Agent": "ClimaTour-Agent/1.0 (projeto educacional)"}

# Orçamento de execução pedido ao servidor, em segundos: vira ``[timeout:N]``
# na query. O valor antigo (25s) era menor que o custo real da consulta em
# cidades densas, o que fazia o servidor abortar e devolver lista vazia.
#
# Por que 50 e não mais: tempos medidos com a consulta por bbox foram 2,1s em
# Ouro Preto, 3,3s em Copacabana e 10,3s em Belo Horizonte, ou seja, folga
# grande para o caso normal. Só a Sé (São Paulo) não cabe em raio de 3 km, e
# para ela o que importa é falhar rápido e cair no plano B: com orçamento de
# 90s a resposta levava 145,7s, tempo demais para o spinner do Streamlit.
OVERPASS_SERVER_TIMEOUT = 50

# Timeout de conexão curto: um espelho fora do ar falha rápido em vez de
# pendurar a aplicação inteira (foi o que o kumi.systems fazia).
OVERPASS_CONNECT_TIMEOUT = 8

# O timeout de leitura precisa ser MAIOR que o orçamento do servidor. Se for
# menor, o cliente desiste antes de o servidor conseguir responder — e o
# usuário recebe "a requisição expirou" em vez do erro real.
OVERPASS_READ_TIMEOUT = OVERPASS_SERVER_TIMEOUT + 20

# Pausa antes de tentar o próximo espelho após 429/504 (o wiki do OSM pede
# que o cliente espere ao receber esses códigos).
PAUSA_APOS_LIMITE = 2

# Teto de tempo para TODA a consulta de atrações: todos os espelhos mais o
# plano B. Sem esse teto, o pior caso seria 3 espelhos x 70s, duas vezes
# (consulta cheia + plano B) — minutos de spinner parado. A carga dos
# servidores públicos varia muito: a mesma consulta em BH levou 10,3s numa
# execução e 96,7s na seguinte, então o limite é por tempo, não por tentativas.
OVERPASS_PRAZO_TOTAL = 150

# Fração do prazo reservada à consulta no raio cheio. O resto fica para o
# plano B, que só serve se ainda houver tempo de rodar.
FRACAO_PRAZO_TENTATIVA_CHEIA = 0.6

# Cache em memória: a mesma cidade é consultada várias vezes numa conversa.
CACHE_TTL_SEGUNDOS = 600
_CACHE: dict[tuple, tuple[float, dict]] = {}

# --------------------------------------------------------------------------
# Categorias de atração. Amplas de propósito: "qualquer tipo de atração".
# --------------------------------------------------------------------------
TURISMO = "attraction|museum|zoo|aquarium|theme_park|viewpoint|gallery|artwork|picnic_site"
GASTRONOMIA_E_CULTURA = (
    "restaurant|cafe|bar|pub|ice_cream|food_court|biergarten|"
    "theatre|cinema|arts_centre|casino|nightclub|"
    "place_of_worship|marketplace|fountain|planetarium"
)
NATUREZA = "beach|peak|cave_entrance|spring|hot_spring|volcano|arch|geyser|cliff|bay|reef|dune"
LAZER = "park|garden|nature_reserve|water_park|beach_resort|marina|stadium"
CONSTRUCOES = "lighthouse|pier|observatory"

# Rótulos legíveis em português, indexados por "chave=valor" do OSM.
CATEGORIAS_PT = {
    # tourism
    "tourism=attraction": "atração turística",
    "tourism=museum": "museu",
    "tourism=zoo": "zoológico",
    "tourism=aquarium": "aquário",
    "tourism=theme_park": "parque temático",
    "tourism=viewpoint": "mirante",
    "tourism=gallery": "galeria de arte",
    "tourism=artwork": "obra de arte pública",
    "tourism=picnic_site": "área de piquenique",
    # amenity
    "amenity=restaurant": "restaurante",
    "amenity=cafe": "café",
    "amenity=bar": "bar",
    "amenity=pub": "pub",
    "amenity=ice_cream": "sorveteria",
    "amenity=food_court": "praça de alimentação",
    "amenity=biergarten": "cervejaria ao ar livre",
    "amenity=theatre": "teatro",
    "amenity=cinema": "cinema",
    "amenity=arts_centre": "centro cultural",
    "amenity=casino": "cassino",
    "amenity=nightclub": "casa noturna",
    "amenity=place_of_worship": "templo religioso",
    "amenity=marketplace": "mercado",
    "amenity=fountain": "fonte",
    "amenity=planetarium": "planetário",
    # historic
    "historic=castle": "castelo",
    "historic=church": "igreja histórica",
    "historic=monument": "monumento",
    "historic=memorial": "memorial",
    "historic=ruins": "ruínas",
    "historic=archaeological_site": "sítio arqueológico",
    "historic=fort": "forte",
    "historic=city_gate": "portal histórico",
    "historic=monastery": "mosteiro",
    "historic=manor": "casarão histórico",
    "historic=aqueduct": "aqueduto",
    "historic=building": "edificação histórica",
    "historic=district": "centro histórico",
    "historic=mine": "mina histórica",
    "historic=tomb": "túmulo histórico",
    "historic=tower": "torre histórica",
    "historic=bridge": "ponte histórica",
    "historic=locomotive": "locomotiva histórica",
    "historic=ship": "navio histórico",
    "historic=wayside_cross": "cruzeiro",
    "historic=wayside_shrine": "capela de beira de estrada",
    # natural
    "natural=beach": "praia",
    "natural=peak": "pico",
    "natural=cave_entrance": "caverna",
    "natural=spring": "nascente",
    "natural=hot_spring": "fonte termal",
    "natural=volcano": "vulcão",
    "natural=arch": "arco natural",
    "natural=geyser": "geiser",
    "natural=cliff": "falésia",
    "natural=bay": "baía",
    "natural=reef": "recife",
    "natural=dune": "duna",
    # leisure
    "leisure=park": "parque",
    "leisure=garden": "jardim",
    "leisure=nature_reserve": "reserva natural",
    "leisure=water_park": "parque aquático",
    "leisure=beach_resort": "balneário",
    "leisure=marina": "marina",
    "leisure=stadium": "estádio",
    # outros
    "waterway=waterfall": "cachoeira",
    "place=square": "praça",
    "man_made=lighthouse": "farol",
    "man_made=pier": "píer",
    "man_made=observatory": "observatório",
}

# Ordem de preferência para rotular a categoria, da mais específica para a mais
# genérica. "tourism" fica no fim porque tourism=attraction é vago: um POI com
# historic=mine + tourism=attraction deve ser rotulado "mina histórica".
CHAVES_CATEGORIA = (
    "historic", "natural", "waterway", "leisure",
    "place", "man_made", "tourism", "amenity",
)

# Valores que existem só para marcar "esta chave se aplica" e não descrevem o
# lugar. Sem isso, "historic=yes" virava a categoria literal "yes".
VALORES_GENERICOS = frozenset({"yes", "true", "1"})

# Rótulo amplo usado quando a chave só tem valor genérico.
ROTULOS_GENERICOS = {
    "historic": "local histórico",
    "tourism": "atração turística",
    "natural": "atração natural",
    "leisure": "área de lazer",
    "waterway": "curso d'água",
    "place": "logradouro",
    "man_made": "construção",
    "amenity": "estabelecimento",
}

# Valores de amenity que também são atrações "de destino", não só alimentação.
AMENITIES_CULTURAIS = frozenset({
    "theatre", "arts_centre", "place_of_worship", "marketplace",
    "planetarium", "cinema", "casino", "fountain",
})

DIAS_SEMANA = {
    "Mo": 0, "Tu": 1, "We": 2, "Th": 3,
    "Fr": 4, "Sa": 5, "Su": 6,
}

# Construções de opening_hours que NÃO sabemos avaliar com segurança.
# Se qualquer uma aparecer, o status vira None (desconhecido).
TOKENS_NAO_SUPORTADOS = (
    "ph", "sh", "sunrise", "sunset", "dawn", "dusk", "easter", "week",
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
    "[", "]", "+",
)

# Seletor de dias no início de uma regra: "Mo", "Mo-Fr", "Mo,We,Fr", ...
_DIA = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)"
_BLOCO_DIAS = rf"(?:{_DIA}(?:-{_DIA})?)"
RE_REGRA = re.compile(
    rf"^((?:{_BLOCO_DIAS})(?:\s*,\s*{_BLOCO_DIAS})*)?\s*(.*)$"
)
RE_FAIXA_HORARIO = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")


def get_attractions(
    lat: float,
    lon: float,
    limite: int = 8,
    raio: int = 3000,
    utc_offset_seconds: int | None = None,
) -> list:
    """
    Busca atrações turísticas próximas de uma coordenada na Overpass API (OSM).

    Abrange pontos turísticos, restaurantes, cafés, bares, centros históricos,
    igrejas, praças, cachoeiras, praias, mirantes, parques e teatros.

    :param lat: Latitude.
    :param lon: Longitude.
    :param limite: Número máximo de atrações retornadas.
    :param raio: Raio de busca em metros. O padrão de 3000 é um equilíbrio
        entre cobertura e latência: em metrópoles densas (ex.: centro de São
        Paulo) raios maiores encarecem muito a consulta na Overpass pública.
        A busca vai ao servidor como uma caixa quadrada e o raio exato é
        aplicado aqui, no cliente.
    :param utc_offset_seconds: Deslocamento do fuso local em segundos (ex.: o
        campo ``timezone`` da OpenWeatherMap). Necessário para avaliar o
        horário na hora LOCAL da atração. Se None, o status de funcionamento
        fica desconhecido para regras que dependem de horário.
    :return: Lista de dicts com ``nome``, ``categoria``, ``aberto``,
        ``horario`` e ``destaque``. ``aberto`` é True, False ou None
        (desconhecido) — nunca deve ser inventado pelo agente.
    """
    dados = _consultar_com_plano_b(lat, lon, raio)
    agora_local = _hora_local(utc_offset_seconds)
    centro_lat, centro_lon, raio_max = float(lat), float(lon), int(raio)

    atracoes, vistos = [], set()
    for elemento in dados.get("elements", []):
        tags = elemento.get("tags", {})
        nome = tags.get("name")
        if not nome or nome in vistos:
            continue

        # A query busca numa caixa quadrada (barato no servidor); aqui
        # recortamos o círculo exato do raio pedido (barato no cliente).
        coord = _coordenada(elemento)
        if coord and _distancia_metros(centro_lat, centro_lon, *coord) > raio_max:
            continue

        vistos.add(nome)

        chave = _chave_categoria(tags)
        expr_horario = tags.get("opening_hours")
        # wikidata/wikipedia indicam POI notável (proxy honesto de relevância).
        destaque = bool(tags.get("wikidata") or tags.get("wikipedia"))

        atracoes.append({
            "nome": nome,
            "categoria": _rotular(tags, chave),
            # None = desconhecido. O agente é instruído a não inventar status.
            "aberto": _avaliar_opening_hours(expr_horario, agora_local),
            "horario": expr_horario,
            "destaque": destaque,
            "_pontos": _pontuar(tags, chave, destaque),
        })

    if not atracoes:
        # Chegar aqui agora significa ausência real de dados no OSM: uma
        # consulta abortada pelo servidor já teria virado TimeoutError em
        # _consultar_overpass, via campo "remark".
        raise ValueError(
            "Nenhuma atração mapeada no OpenStreetMap num raio de "
            f"{raio_max} m destas coordenadas."
        )

    # Ordena por relevância antes de cortar, para não descartar os destaques.
    atracoes.sort(key=lambda a: a["_pontos"], reverse=True)
    for atracao in atracoes:
        del atracao["_pontos"]
    return atracoes[:limite]


# Cada grupo recebe uma COTA própria: (apelido, tipo, filtro, cota).
#
# Sem cota individual, numa cidade grande os restaurantes (centenas) lotariam o
# limite global e eliminariam museus e centros históricos da resposta.
#
# O "tipo" é uma otimização medida na prática. `nwr` (nós + vias + relações)
# obriga o servidor a resolver geometria de vias e relações, o que fica caro em
# áreas densas. Medições no OSM real:
#   - Restaurantes num raio de 3 km em BH: 258 resultados, TODOS nós
#     (ways: 0, relations: 0) -> `node` basta para gastronomia, que é justamente
#     a categoria mais densa.
#   - POIs históricos em Ouro Preto: 34, sendo 3 RELAÇÕES -> aqui `nwr` é
#     obrigatório, senão perderíamos atrações.
GRUPOS_BUSCA = (
    ("t", "nwr", f'["tourism"~"^({TURISMO})$"]', 50),
    ("h", "nwr", '["historic"]', 50),
    ("n", "nwr", f'["natural"~"^({NATUREZA})$"]', 30),
    ("w", "nwr", '["waterway"="waterfall"]', 30),
    ("l", "nwr", f'["leisure"~"^({LAZER})$"]', 30),
    ("m", "nwr", f'["man_made"~"^({CONSTRUCOES})$"]', 15),
    ("p", "nwr", '["place"="square"]', 20),
    ("a", "node", f'["amenity"~"^({GASTRONOMIA_E_CULTURA})$"]', 50),
)


def _caixa_delimitadora(lat: float, lon: float, raio_m: int) -> tuple:
    """
    Converte centro + raio em metros numa caixa (sul, oeste, norte, leste).

    A caixa circunscreve o círculo, então cobre ~27% de área a mais. Isso é
    proposital: o filtro exato pelo raio é feito no cliente
    (``_distancia_metros``), que é grátis, em vez de no servidor, que é o
    recurso escasso.
    """
    graus_lat = raio_m / 111_320.0
    # Perto dos polos o cosseno tende a zero; o piso evita divisão explosiva.
    cos_lat = max(math.cos(math.radians(lat)), 0.01)
    graus_lon = raio_m / (111_320.0 * cos_lat)
    return (lat - graus_lat, lon - graus_lon, lat + graus_lat, lon + graus_lon)


def _montar_query(
    lat: float,
    lon: float,
    raio: int,
    orcamento: int = OVERPASS_SERVER_TIMEOUT,
    fator_cota: float = 1.0,
) -> str:
    """
    Monta a query Overpass QL cobrindo todas as categorias de atração.

    Usa ``nwr`` (nós, vias E relações): em Ouro Preto, por exemplo, 3 dos 34
    POIs históricos são relações e seriam perdidos numa busca só por nós/vias.

    Cada grupo é guardado num conjunto nomeado com ``out`` próprio, garantindo
    cota individual por categoria.

    Filtra por caixa delimitadora em vez de ``around:``. ``around`` calcula
    distância para cada candidato e foi o que estourou o orçamento de 25s da
    versão anterior; a caixa é resolvida pelo índice espacial do servidor.

    :param orcamento: valor de ``[timeout:N]``, o tempo que o servidor pode
        gastar antes de abortar a consulta e responder com ``remark``.
    :param fator_cota: multiplicador das cotas por grupo. Usado no plano B,
        quando a consulta completa não cabe no orçamento.
    """
    # Coerção numérica: evita injeção de texto arbitrário na query.
    lat_f, lon_f, raio_i = float(lat), float(lon), int(raio)
    sul, oeste, norte, leste = _caixa_delimitadora(lat_f, lon_f, raio_i)
    caixa = f"{sul:.6f},{oeste:.6f},{norte:.6f},{leste:.6f}"

    buscas = "\n    ".join(
        f'{tipo}({caixa}){filtro}["name"]->.{apelido};'
        for apelido, tipo, filtro, _ in GRUPOS_BUSCA
    )
    saidas = "\n    ".join(
        f".{apelido} out tags center {max(5, int(cota * fator_cota))};"
        for apelido, _, _, cota in GRUPOS_BUSCA
    )

    return f"""
    [out:json][timeout:{int(orcamento)}];
    {buscas}
    {saidas}
    """


def _chave_categoria(tags: dict) -> str | None:
    """
    Descobre qual chave do OSM melhor define a categoria deste POI.

    ``tourism`` tem prioridade quando traz um valor específico (museum, zoo),
    mas perde para chaves mais descritivas quando é apenas "attraction".

    Chaves com valor genérico (``historic=yes``) ficam para a segunda passada:
    a Biblioteca Pública de BH, por exemplo, tem ``historic=yes`` e aparecia
    rotulada literalmente como "yes".
    """
    turismo = tags.get("tourism")
    if turismo and turismo != "attraction" and turismo not in VALORES_GENERICOS:
        return "tourism"

    # 1ª passada: prefere chave cujo valor descreve de fato o lugar.
    for chave in CHAVES_CATEGORIA:
        valor = tags.get(chave)
        if valor and valor not in VALORES_GENERICOS:
            return chave

    # 2ª passada: aceita valor genérico, rotulado de forma ampla em _rotular.
    for chave in CHAVES_CATEGORIA:
        if chave in tags:
            return chave
    return None


def _rotular(tags: dict, chave: str | None) -> str:
    """Traduz a categoria do OSM para um rótulo legível em português."""
    if not chave:
        return "ponto de interesse"

    valor = tags.get(chave, "")
    rotulo = CATEGORIAS_PT.get(f"{chave}={valor}")
    if rotulo:
        return rotulo

    # "historic=yes" não diz nada ao usuário: usa o rótulo amplo da chave.
    if not valor or valor in VALORES_GENERICOS:
        return ROTULOS_GENERICOS.get(chave, "ponto de interesse")

    return valor.replace("_", " ")


def _pontuar(tags: dict, chave: str | None, destaque: bool) -> int:
    """
    Pontua a relevância do POI para ordenar os resultados.

    O OSM não tem avaliações nem popularidade, então não existe "restaurante
    famoso" como dado. Usamos sinais reais como aproximação: presença em
    wikidata/wikipedia, ser atração de destino, ter horário e site publicados.
    """
    pontos = 0
    if destaque:
        pontos += 3
    # Atração "de destino" pontua mais que um estabelecimento de alimentação.
    if chave != "amenity" or tags.get("amenity") in AMENITIES_CULTURAIS:
        pontos += 2
    if tags.get("opening_hours"):
        pontos += 2
    if tags.get("heritage") or tags.get("heritage:operator"):
        pontos += 1
    if tags.get("website") or tags.get("contact:website"):
        pontos += 1
    return pontos


def _consultar_overpass(query: str, prazo: float | None = None) -> dict:
    """
    Executa a query na Overpass API, tentando os espelhos em ordem.

    Não há autenticação: a Overpass é anônima. O único cabeçalho obrigatório é
    o ``User-Agent`` exigido pela política de uso do OSM.

    :param prazo: instante de ``time.monotonic()`` em que se deve parar de
        tentar novos espelhos. Impede que 4 espelhos lentos somem minutos de
        espera. Se None, usa o prazo padrão a partir de agora.
    :return: JSON da Overpass.
    :raise: a exceção do último espelho, se todos falharem.
    """
    if prazo is None:
        prazo = time.monotonic() + OVERPASS_PRAZO_TOTAL

    ultimo_erro = None

    for endpoint in OVERPASS_ENDPOINTS:
        restante = prazo - time.monotonic()
        # Sem tempo nem para abrir a conexão: para de queimar espelhos.
        if restante <= OVERPASS_CONNECT_TIMEOUT:
            ultimo_erro = ultimo_erro or TimeoutError(
                "Tempo esgotado ao consultar a API de atrações."
            )
            break

        try:
            response = requests.post(
                endpoint,
                data={"data": query},
                headers=HEADERS,
                # (conexão, leitura): a leitura precisa ser maior que o
                # orçamento do servidor para receber o erro real dele, mas
                # nunca maior que o tempo que ainda resta.
                timeout=(
                    OVERPASS_CONNECT_TIMEOUT,
                    min(OVERPASS_READ_TIMEOUT, restante),
                ),
            )
            response.raise_for_status()
            dados = response.json()

            # ARMADILHA PRINCIPAL DESTA API, e a causa do bug original:
            # quando a consulta estoura o [timeout:N] ou a memória, a Overpass
            # responde HTTP 200 com "elements": [] e um campo "remark"
            # descrevendo o erro. Sem checar "remark", o código concluía
            # "nenhuma atração existe aqui" para um erro de servidor.
            remark = dados.get("remark")
            if remark:
                ultimo_erro = TimeoutError(
                    "A Overpass API interrompeu a consulta de atrações "
                    f"(servidor {endpoint.split('/')[2]}): {remark.strip()}"
                )
                continue

            return dados

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            # 429 (rate limit), 504 (sobrecarga) e 503 são comuns na Overpass:
            # vale pausar e tentar o próximo espelho.
            if status in (429, 503, 504):
                ultimo_erro = ConnectionError(
                    "Overpass API: limite de requisições atingido ou servidor "
                    "sobrecarregado. Tente novamente em alguns instantes."
                )
                time.sleep(PAUSA_APOS_LIMITE)
                continue
            ultimo_erro = RuntimeError(f"Erro HTTP ao buscar atrações: {e}")
            continue

        except requests.exceptions.Timeout:
            ultimo_erro = TimeoutError(
                "A requisição para a API de atrações expirou em "
                f"{endpoint.split('/')[2]}."
            )
            continue

        except ValueError as e:
            # Resposta não era JSON válido (ex.: página de erro em HTML).
            ultimo_erro = RuntimeError(f"Resposta inválida da Overpass API: {e}")
            continue

        except requests.exceptions.RequestException as e:
            ultimo_erro = RuntimeError(f"Erro de conexão ao buscar atrações: {e}")
            continue

    raise ultimo_erro or RuntimeError("Falha ao consultar a Overpass API.")


def _consultar_com_plano_b(lat: float, lon: float, raio: int) -> dict:
    """
    Consulta a Overpass e, se a consulta completa não couber no orçamento do
    servidor, tenta de novo com uma área menor.

    Metade do raio é um quarto da área, o que reduz drasticamente o custo. É
    melhor devolver menos atrações reais do que falhar a recomendação inteira.
    """
    chave = (round(float(lat), 3), round(float(lon), 3), int(raio))
    em_cache = _CACHE.get(chave)
    if em_cache and (time.monotonic() - em_cache[0]) < CACHE_TTL_SEGUNDOS:
        return em_cache[1]

    inicio = time.monotonic()
    prazo_final = inicio + OVERPASS_PRAZO_TOTAL
    prazo_cheia = inicio + OVERPASS_PRAZO_TOTAL * FRACAO_PRAZO_TENTATIVA_CHEIA

    try:
        dados = _consultar_overpass(_montar_query(lat, lon, raio), prazo_cheia)
    except (TimeoutError, ConnectionError) as erro_original:
        raio_reduzido = max(1200, int(raio) // 2)
        if raio_reduzido >= int(raio):
            raise
        try:
            dados = _consultar_overpass(
                _montar_query(lat, lon, raio_reduzido, fator_cota=0.5),
                prazo_final,
            )
        except Exception:
            # O erro da tentativa completa explica melhor o problema.
            raise erro_original

    _CACHE[chave] = (time.monotonic(), dados)
    return dados


def _coordenada(elemento: dict) -> tuple | None:
    """
    Extrai lat/lon de um elemento do OSM.

    Nós trazem ``lat``/``lon`` direto; vias e relações trazem ``center``,
    porque a query pede ``out ... center``.
    """
    if "lat" in elemento and "lon" in elemento:
        return elemento["lat"], elemento["lon"]
    centro = elemento.get("center") or {}
    if "lat" in centro and "lon" in centro:
        return centro["lat"], centro["lon"]
    return None


def _distancia_metros(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância Haversine em metros entre dois pontos."""
    raio_terra = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = phi2 - phi1
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * raio_terra * math.asin(math.sqrt(a))


def _hora_local(utc_offset_seconds: int | None) -> datetime | None:
    """
    Converte o instante atual para a hora local da atração.

    :return: ``datetime`` naive na hora local, ou None se o fuso é desconhecido.
    """
    if utc_offset_seconds is None:
        return None
    agora_utc = datetime.now(timezone.utc)
    return (agora_utc + timedelta(seconds=int(utc_offset_seconds))).replace(tzinfo=None)


def _avaliar_opening_hours(expr: str | None, agora: datetime | None) -> bool | None:
    """
    Avalia a expressão ``opening_hours`` do OSM no instante informado.

    Deliberadamente conservador: retorna None sempre que a expressão usa
    construções que não sabemos avaliar (feriados, meses, sunrise/sunset,
    semanas específicas), para não afirmar um status incorreto.

    :return: True (aberta), False (fechada) ou None (desconhecido).
    """
    if not expr or not expr.strip():
        return None

    texto = expr.strip()
    baixo = texto.lower()

    # 24/7 não depende de saber a hora local.
    if baixo in ("24/7", "24x7", "mo-su 00:00-24:00", "00:00-24:00"):
        return True

    if agora is None:
        return None

    if any(token in baixo for token in TOKENS_NAO_SUPORTADOS):
        return None

    dia_atual = agora.weekday()          # 0 = segunda
    minuto_atual = agora.hour * 60 + agora.minute

    # Regras posteriores sobrescrevem as anteriores (semântica do OSM).
    resultado = None
    for regra in texto.split(";"):
        regra = regra.strip()
        if not regra:
            continue
        parcial = _avaliar_regra(regra, dia_atual, minuto_atual)
        if parcial is not None:
            resultado = parcial
    return resultado


def _avaliar_regra(regra: str, dia_atual: int, minuto_atual: int) -> bool | None:
    """
    Avalia uma única regra de ``opening_hours``.

    :return: True/False se a regra se aplica a hoje, None se não se aplica ou
        se não foi possível interpretá-la.
    """
    match = RE_REGRA.match(regra)
    if not match:
        return None

    dias_txt, resto = match.group(1), (match.group(2) or "").strip()

    # Sem seletor de dias, a regra vale para todos os dias.
    if dias_txt:
        dias = _parse_dias(dias_txt)
        if dias is None:
            return None
        if dia_atual not in dias:
            return None

    baixo = resto.lower()
    if baixo in ("off", "closed"):
        return False
    if baixo in ("open", "24/7", "00:00-24:00"):
        return True
    if not resto:
        return None

    return _avaliar_faixas(resto, minuto_atual)


def _parse_dias(dias_txt: str) -> set | None:
    """Converte "Mo-Fr" / "Mo,We" em um conjunto de índices de dia (0=segunda)."""
    dias = set()
    for bloco in dias_txt.split(","):
        bloco = bloco.strip()
        try:
            if "-" in bloco:
                inicio_txt, fim_txt = bloco.split("-", 1)
                inicio, fim = DIAS_SEMANA[inicio_txt.strip()], DIAS_SEMANA[fim_txt.strip()]
                if inicio <= fim:
                    dias.update(range(inicio, fim + 1))
                else:
                    # Intervalo que dá a volta na semana, ex.: "Sa-Mo".
                    dias.update(list(range(inicio, 7)) + list(range(0, fim + 1)))
            else:
                dias.add(DIAS_SEMANA[bloco])
        except KeyError:
            return None
    return dias


def _avaliar_faixas(resto: str, minuto_atual: int) -> bool | None:
    """
    Verifica se ``minuto_atual`` cai em alguma faixa de horário da regra.

    :return: True se está dentro de alguma faixa, False se está fora de todas,
        None se alguma faixa não pôde ser interpretada.
    """
    for faixa in resto.split(","):
        match = RE_FAIXA_HORARIO.match(faixa.strip())
        if not match:
            # Formato inesperado: não arriscamos afirmar o status.
            return None

        h_ini, m_ini, h_fim, m_fim = (int(g) for g in match.groups())
        inicio, fim = h_ini * 60 + m_ini, h_fim * 60 + m_fim

        if fim <= inicio:
            # Faixa que atravessa a meia-noite, ex.: "22:00-02:00".
            if minuto_atual >= inicio or minuto_atual < fim:
                return True
        elif inicio <= minuto_atual < fim:
            return True

    return False
