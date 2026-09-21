"""
Cache em disco (SQLite) para respostas da API de atrações.

Por que existe: o cache anterior vivia só na memória do processo. Ele se perdia
a cada reinício da aplicação e não era compartilhado entre execuções, então a
primeira pergunta sobre qualquer cidade sempre pagava a latência cheia da
Overpass — que tem cauda longa (medido na mesma consulta: 1,9s, 2,6s e 33,9s).
Com o cache em disco, essa cauda é paga UMA vez por cidade, e não a cada sessão.

Usa apenas a biblioteca padrão (``sqlite3``, ``zlib``): nenhuma dependência nova.

Duas decisões importantes:

1. Guardamos a resposta CRUA do servidor, não a lista de atrações já montada.
   O campo ``aberto`` depende da hora atual, então precisa ser recalculado a
   cada leitura. Se guardássemos o resultado processado, o status de
   aberto/fechado congelaria no momento da gravação — e passaria a mentir.
   Como o dado cru muda devagar (base do OpenStreetMap), o TTL pode ser longo.

2. Falha de cache NUNCA derruba a aplicação. Todo acesso é envolvido em
   ``try/except``: se o banco estiver corrompido, o disco cheio ou somente
   leitura (caso comum em contêineres), a função simplesmente devolve None e o
   fluxo segue para a rede, como se não houvesse cache.
"""

import json
import os
import sqlite3
import time
import zlib

# Caminho do banco. Configurável por variável de ambiente para permitir apontar
# para um volume persistente em produção.
CAMINHO = os.getenv("CLIMATOUR_CACHE_PATH", ".climatour_cache.sqlite3")

# Atrações do OpenStreetMap mudam devagar, e o status de funcionamento é
# recalculado na leitura, então uma semana é seguro e cobre bem um demo.
TTL_PADRAO = 7 * 24 * 3600

# Nível de compressão do zlib. A resposta da Overpass é JSON verboso e repetitivo
# (centenas de POIs com tags), então comprime muito bem.
NIVEL_COMPRESSAO = 6

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS respostas (
    chave     TEXT PRIMARY KEY,
    criado_em REAL NOT NULL,
    conteudo  BLOB NOT NULL
)
"""


def _conectar() -> sqlite3.Connection:
    """
    Abre uma conexão nova e garante o esquema.

    Uma conexão por operação (em vez de uma global) evita problemas de uso
    entre threads — o Streamlit atende cada interação numa thread própria.
    """
    conexao = sqlite3.connect(CAMINHO, timeout=5)
    conexao.execute(_ESQUEMA)
    return conexao


def obter(chave: str, ttl: int = TTL_PADRAO) -> dict | None:
    """
    Devolve o valor guardado para ``chave``, ou None se ausente/expirado.

    Qualquer erro de acesso resulta em None: o cache é um acelerador opcional,
    nunca um ponto de falha.
    """
    try:
        with _conectar() as conexao:
            linha = conexao.execute(
                "SELECT criado_em, conteudo FROM respostas WHERE chave = ?",
                (chave,),
            ).fetchone()

        if not linha:
            return None

        criado_em, conteudo = linha
        if (time.time() - criado_em) > ttl:
            return None

        return json.loads(zlib.decompress(conteudo).decode("utf-8"))

    except Exception:
        return None


def guardar(chave: str, valor: dict) -> None:
    """
    Grava ``valor`` sob ``chave``, sobrescrevendo o que houver.

    Silencia erros de escrita de propósito: em ambientes com sistema de
    arquivos somente leitura a aplicação deve continuar funcionando sem cache.
    """
    try:
        bruto = json.dumps(valor, ensure_ascii=False).encode("utf-8")
        comprimido = zlib.compress(bruto, NIVEL_COMPRESSAO)
        with _conectar() as conexao:
            conexao.execute(
                "INSERT OR REPLACE INTO respostas (chave, criado_em, conteudo) "
                "VALUES (?, ?, ?)",
                (chave, time.time(), comprimido),
            )
    except Exception:
        pass


def limpar_expirados(ttl: int = TTL_PADRAO) -> int:
    """
    Remove entradas vencidas e devolve quantas saíram.

    Não é chamado automaticamente: serve para manutenção, caso o banco cresça.
    """
    try:
        limite = time.time() - ttl
        with _conectar() as conexao:
            cursor = conexao.execute(
                "DELETE FROM respostas WHERE criado_em < ?", (limite,)
            )
            return cursor.rowcount or 0
    except Exception:
        return 0
