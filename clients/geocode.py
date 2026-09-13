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
    :param api_key: Your OpenWeatherMap API key
    :return: Tuple containing latitude and longitude
    """
    if not api_key:
        raise ValueError("API key is required")

    url = f"http://api.openweathermap.org/geo/1.0/direct?q={city_name},{state_code},{country_code}&limit={limit}&appid={api_key}"

    
    response = requests.get(url)

    if response.status_code == 200:
        geo_data = response.json()
        return geo_data[0]['lat'], geo_data[0]['lon']
    else:
        response.raise_for_status()

