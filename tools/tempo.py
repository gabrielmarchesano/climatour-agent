"""
Resolução de fuso horário e datas em linguagem natural.

Por que este módulo existe
--------------------------
O agente não tinha NENHUMA noção de data: nada no ``SYSTEM_PROMPT`` nem nas
ferramentas dizia que dia é hoje. O modelo então respondia "hoje" e "amanhã"
chutando a partir do próprio treinamento — daí respostas como "o relógio
interno do sistema indica que hoje é ...", com hedging sobre o calendário do
usuário estar desatualizado.

Além disso o servidor que hospeda o Streamlit não fica necessariamente no mesmo
fuso de quem acessa o app (tipicamente ele roda em UTC). Usar a hora do
servidor erraria o dia inteiro perto da meia-noite: às 22h20 em Brasília já é o
dia seguinte em UTC.

A solução é ancorar tudo em dois fusos explícitos:
  - o fuso do NAVEGADOR do usuário, que define o que é "hoje" e "amanhã";
  - o fuso da CIDADE consultada, que define a hora local da previsão.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo

try:  # zoneinfo é stdlib desde o Python 3.9
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - ambiente muito antigo
    ZoneInfo = None  # type: ignore[assignment]


# datetime.weekday(): 0 = segunda ... 6 = domingo
DIAS_SEMANA_PT = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)


def resolver_fuso(
    nome: str | None = None,
    offset_minutos: int | float | None = None,
) -> tzinfo:
    """
    Resolve o fuso do usuário, do mais confiável para o menos confiável.

    1. Nome IANA (ex.: "America/Sao_Paulo"). Preferido porque carrega as regras
       de horário de verão, e não apenas o deslocamento de agora.
    2. Deslocamento em minutos, na convenção do JavaScript usada por
       ``st.context.timezone_offset``: o valor é positivo quando o fuso está
       ATRÁS de UTC (Brasília = 180), por isso o sinal é invertido aqui.
    3. UTC, como último recurso.

    :param nome: identificador IANA do fuso, se disponível.
    :param offset_minutos: deslocamento do navegador, em minutos.
    :return: um ``tzinfo`` utilizável em ``astimezone``.
    """
    if nome and ZoneInfo is not None:
        try:
            return ZoneInfo(str(nome))
        except Exception:
            # Nome desconhecido ou base de fusos (tzdata) ausente no sistema:
            # cai para o deslocamento numérico, que não depende de base local.
            pass

    if offset_minutos is not None:
        try:
            return timezone(-timedelta(minutes=int(offset_minutos)))
        except (TypeError, ValueError):
            pass

    return timezone.utc


def fuso_por_offset_segundos(offset_segundos: int | float | None) -> tzinfo | None:
    """
    Converte o deslocamento em segundos devolvido pela OpenWeatherMap
    (``timezone`` / ``city.timezone``) em um ``tzinfo``.

    Aqui o sinal é o convencional (positivo = à frente de UTC), diferente da
    convenção do navegador tratada em :func:`resolver_fuso`.

    :return: ``tzinfo`` ou None quando o deslocamento é desconhecido.
    """
    if offset_segundos is None:
        return None
    try:
        return timezone(timedelta(seconds=int(offset_segundos)))
    except (TypeError, ValueError):
        return None


def agora_no_fuso(fuso: tzinfo) -> datetime:
    """Instante atual convertido para o fuso informado (sempre consciente)."""
    return datetime.now(timezone.utc).astimezone(fuso)


def dia_semana_pt(momento: datetime) -> str:
    """Nome do dia da semana em português."""
    return DIAS_SEMANA_PT[momento.weekday()]


def rotulo_offset(momento: datetime) -> str:
    """Formata o deslocamento de um datetime consciente como 'UTC-03:00'."""
    desloc = momento.utcoffset() or timedelta(0)
    total = int(desloc.total_seconds())
    sinal = "+" if total >= 0 else "-"
    total = abs(total)
    return f"UTC{sinal}{total // 3600:02d}:{(total % 3600) // 60:02d}"


def bloco_data_atual(
    fuso_nome: str | None = None,
    fuso_offset_minutos: int | float | None = None,
    dias: int = 7,
) -> str:
    """
    Monta o trecho de prompt que informa ao modelo a data e a hora atuais no
    fuso do usuário, com o calendário dos próximos dias já resolvido.

    O calendário explícito evita que o modelo tenha que fazer aritmética de
    datas (onde ele erra com frequência) para entender "amanhã", "sexta" ou
    "fim de semana": basta ler a linha correspondente.

    :param fuso_nome: nome IANA do fuso do navegador.
    :param fuso_offset_minutos: deslocamento do navegador, em minutos.
    :param dias: quantos dias listar no calendário.
    :return: texto pronto para concatenar ao system prompt.
    """
    fuso = resolver_fuso(fuso_nome, fuso_offset_minutos)
    agora = agora_no_fuso(fuso)
    desloc = rotulo_offset(agora)

    if fuso_nome:
        identificacao = f"{fuso_nome}, {desloc}"
    elif fuso_offset_minutos is not None:
        identificacao = desloc
    else:
        # Nem nome nem deslocamento: o valor cai em UTC. Vale ser explícito com
        # o modelo, para ele poder confirmar a data com o usuário se o horário
        # for decisivo (ex.: um passeio hoje à noite).
        identificacao = f"{desloc} — fuso do navegador indisponível, assumindo UTC"

    linhas = [
        f"DATA E HORA ATUAIS (fuso do usuário: {identificacao}):",
        f"- Agora são {agora.strftime('%H:%M')} de "
        f"{dia_semana_pt(agora)}, {agora.strftime('%d/%m/%Y')}.",
        "- Calendário já resolvido (use estas datas, não calcule por conta):",
    ]

    for passo in range(max(1, dias)):
        dia = agora + timedelta(days=passo)
        if passo == 0:
            rotulo = "hoje"
        elif passo == 1:
            rotulo = "amanhã"
        elif passo == 2:
            rotulo = "depois de amanhã"
        else:
            rotulo = dia_semana_pt(dia)
        linhas.append(
            f"    - {rotulo}: {dia.strftime('%d/%m/%Y')} "
            f"({dia_semana_pt(dia)})"
        )

    linhas += [
        "",
        "REGRAS DE DATA:",
        "- As datas acima são a única fonte da verdade sobre o dia de hoje. "
        "NÃO use seu conhecimento interno para supor a data atual.",
        "- NUNCA diga que a data vem do 'relógio interno do sistema', nem "
        "sugira que o calendário do usuário está errado, atrasado ou "
        "desatualizado. A data acima já está no fuso dele.",
        "- Ao ler a previsão, use o campo `data_hora_local` (hora local da "
        "cidade) e cruze com o calendário acima. Ignore qualquer horário em "
        "UTC.",
        "- Se a cidade do passeio estiver em um fuso diferente do usuário, o "
        "campo `agora_local` da ferramenta diz a hora na cidade; 'hoje' e "
        "'amanhã' continuam valendo pelo calendário do usuário acima.",
        "- Se a previsão não cobrir a data pedida (a previsão alcança cerca de "
        "5 dias), diga isso claramente em vez de estimar o tempo.",
    ]
    return "\n".join(linhas)
