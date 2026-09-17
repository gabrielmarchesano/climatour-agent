import os
import requests
from dotenv import load_dotenv

load_dotenv()

# Chave gratuita da OpenTripMap (https://opentripmap.io).
# Adicione ATTRACTIONS_API_KEY ao seu .env para usar a busca de atrações.
api_key = os.getenv("ATTRACTIONS_API_KEY")


def get_attractions(lat: float, lon: float, limite: int = 5) -> list:
    """
    Busca atrações turísticas próximas de uma coordenada usando a OpenTripMap.

    :param lat: Latitude
    :param lon: Longitude
    :param limite: Número máximo de atrações
    :return: Lista de dicts com nome, categoria e status (aberto/fechado)
    """
    if not api_key:
        raise ValueError("API key is required")

    url = (
        "https://api.opentripmap.com/0.1/en/places/radius"
        f"?radius=5000&lon={lon}&lat={lat}&kinds=tourist_facilities"
        f"&limit={limite}&format=json&apikey={api_key}"
    )

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        dados = response.json()
        if not dados:
            raise ValueError("Nenhuma atração encontrada para estas coordenadas.")

        atracoes = []
        for item in dados:
            nome = item.get("name")
            if not nome:
                # Dados de OSM frequentemente vêm sem nome; ignoramos.
                continue
            atracoes.append({
                "nome": nome,
                "categoria": item.get("kinds", ""),
                # O endpoint radius não expõe status aberto/fechado;
                # deixamos None para o agente não inventar.
                "aberto": None,
            })
        return atracoes

    except requests.exceptions.HTTPError as e:
        if response.status_code in (401, 403):
            raise PermissionError("OpenTripMap: Chave de API inválida ou sem permissão.")
        elif response.status_code == 404:
            raise ValueError("OpenTripMap: Atrações não encontradas para estas coordenadas.")
        elif response.status_code == 429:
            raise ConnectionError("OpenTripMap: Limite de requisições excedido (Rate Limit).")
        raise RuntimeError(f"Erro HTTP ao buscar atrações: {e}")

    except requests.exceptions.Timeout:
        raise TimeoutError("A requisição para a API de atrações expirou.")

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Erro de conexão ao buscar atrações: {e}")
