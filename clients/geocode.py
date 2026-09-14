import requests
import os
from dotenv import load_dotenv

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
    """
    if not api_key:
        raise ValueError("API key is required")

    url = f"http://api.openweathermap.org/geo/1.0/direct?q={city_name},{state_code},{country_code}&limit={limit}&appid={api_key}"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raise an error for bad responses

        geo_data = response.json()

        if not geo_data:
            raise ValueError("No weather data found for the given coordinates")
        return geo_data[0]['lat'], geo_data[0]['lon']    
    except requests.exceptions.RequestException as e:
        if response.status_code == 401:
            raise PermissionError("OpenWeatherMap: Chave de API inválida ou sem permissão.")
        elif response.status_code == 429:
            raise ConnectionError("OpenWeatherMap: Limite de requisições excedido (Rate Limit).")
        raise RuntimeError(f"Erro HTTP na API de geolocalização: {e}")

    except requests.exceptions.Timeout:
        raise TimeoutError("A requisição para a API de geolocalização expirou.")
    
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Erro de conexão ao buscar coordenadas: {e}")
    
    except KeyError as e:
        raise ValueError(f"Formato de resposta inesperado da API. Chave ausente: {e}")

