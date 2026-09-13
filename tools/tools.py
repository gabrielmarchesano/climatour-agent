from langchain.tools import tool
from clients.geocode import get_cordinates
from clients.weather import get_weather_data

@tool
def get_clima(cidade: str, uf: str) -> dict:
    """
    Retorna as condições climáticas atuais de uma cidade brasileira.
    Use esta ferramenta para saber se está chovendo, a temperatura
    e o clima geral de uma cidade específica dentro de um estado.
    """
    lat, lon = get_cordinates(cidade, uf, "BR")
    clima = get_weather_data(lat, lon)
    return clima