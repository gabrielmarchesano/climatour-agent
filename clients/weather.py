import requests
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("WEATHER_API_KEY")

def get_weather_data(lat, lon, api_key=None) -> dict:
    """
    Get weather data for a given latitude and longitude using the OpenWeatherMap API.

    :param lat: Latitude
    :param lon: Longitude
    :param api_key: Your OpenWeatherMap API key
    :return: JSON response containing weather data  
    """
    if not api_key:
        raise ValueError("API key is required")

    url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&units=metric&appid={api_key}"

    response = requests.get(url)

    if response.status_code == 200:
        return response.json()
    else:
        response.raise_for_status()


print(get_weather_data(40.7128, -74.0060, api_key=api_key)) 