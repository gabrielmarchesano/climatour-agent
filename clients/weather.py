import requests
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("WEATHER_API_KEY")

def get_weather_data(lat, lon) -> dict:
    """
    Get weather data for a given latitude and longitude using the OpenWeatherMap API.

    :param lat: Latitude
    :param lon: Longitude
    :return: JSON response containing weather data
    """
    if not api_key:
        raise ValueError("API key is required")

    url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&units=metric&appid={api_key}"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raise an error for bad responses

        weather_data = response.json()

        if not weather_data:
            raise ValueError("No weather data found for the given coordinates")
        return weather_data
    except requests.exceptions.HTTPError as e:
        if response.status_code == 401:
            raise PermissionError("OpenWeatherMap: Chave de API inválida ou sem permissão.")
        elif response.status_code == 404:
            raise ValueError("OpenWeatherMap: Dados climáticos não encontrados para estas coordenadas.")
        elif response.status_code == 429:
            raise ConnectionError("OpenWeatherMap: Limite de requisições excedido (Rate Limit).")
        raise RuntimeError(f"Erro HTTP ao buscar clima: {e}")
        
    except requests.exceptions.Timeout:
        raise TimeoutError("A requisição para a API de clima expirou.")
        
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Erro de conexão ao buscar clima: {e}")


