import requests
import os
from dotenv import load_dotenv

from clients.erros import LimiteDeRequisicoesDeDados

load_dotenv()

api_key = os.getenv("WEATHER_API_KEY")

def get_cordinates(city_name: str, state_code: str, country_code: str, limit=1) -> tuple:
    """
    Get geocode information for a given city, state, and country using the OpenWeatherMap API.

    :param city_name: Name of the city
    :param state_code: State code (optional)
    :param country_code: Country code
    :param limit: Number of results to return (default is 1)

    :return: Tuple containing latitude and longitude

    :raise PermissionError: chave de API inválida (401).
    :raise ConnectionError: limite de requisições excedido (429).
    :raise TimeoutError: a requisição expirou.
    :raise ValueError: cidade não encontrada ou resposta em formato inesperado.
    :raise RuntimeError: falha de rede ou erro HTTP não previsto.
    """
    if not api_key:
        raise ValueError("API key is required")

    url = f"http://api.openweathermap.org/geo/1.0/direct?q={city_name},{state_code},{country_code}&limit={limit}&appid={api_key}"

    local = f"{city_name}, {state_code}, {country_code}"

    # Etapa 1: a requisição. Separada do tratamento do corpo porque os modos de
    # falha são diferentes — aqui a resposta pode nem existir.
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

    except requests.exceptions.HTTPError as e:
        # Só raise_for_status() levanta HTTPError, então existe uma resposta.
        # O status é lido de e.response (e não da variável local) para não
        # depender de a atribuição ter acontecido.
        status = e.response.status_code if e.response is not None else None
        if status == 401:
            raise PermissionError(
                "OpenWeatherMap: Chave de API inválida ou sem permissão."
            ) from e
        if status == 404:
            raise ValueError(
                f"OpenWeatherMap: cidade não encontrada ({local})."
            ) from e
        if status == 429:
            # Limite da API de GEOCODIFICAÇÃO, não do provedor de LLM.
            raise LimiteDeRequisicoesDeDados(
                "OpenWeatherMap: Limite de requisições excedido (Rate Limit)."
            ) from e
        raise RuntimeError(f"Erro HTTP na API de geolocalização: {e}") from e

    # Timeout PRECISA vir antes de RequestException: é subclasse dela, e na
    # ordem inversa este bloco nunca seria alcançado.
    except requests.exceptions.Timeout as e:
        raise TimeoutError(
            "A requisição para a API de geolocalização expirou."
        ) from e

    except requests.exceptions.RequestException as e:
        # Conexão recusada, DNS, TLS: a resposta não existe, então nenhum
        # status pode ser consultado aqui.
        raise RuntimeError(f"Erro de conexão ao buscar coordenadas: {e}") from e

    # Etapa 2: o corpo. Uma resposta 200 com conteúdo inesperado é problema de
    # formato, não de rede, e merece uma mensagem que diga isso.
    try:
        geo_data = response.json()
    except ValueError as e:
        # Cobre a JSONDecodeError do requests, que herda de ValueError.
        raise ValueError(
            f"A API de geolocalização devolveu um corpo que não é JSON: {e}"
        ) from e

    if not geo_data:
        # Lista vazia é como a API sinaliza "não achei esta cidade".
        raise ValueError(
            f"OpenWeatherMap: nenhuma localidade encontrada para {local}."
        )

    try:
        return geo_data[0]["lat"], geo_data[0]["lon"]
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(
            "Formato de resposta inesperado da API de geolocalização "
            f"({type(e).__name__}: {e})."
        ) from e

