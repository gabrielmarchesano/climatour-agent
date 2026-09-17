from langchain.tools import tool
from clients.geocode import get_cordinates
from clients.weather import get_weather_data, get_forecast_data
from clients.attractions import get_attractions

@tool
def get_clima(cidade: str, uf: str, country: str) -> dict:
    """
    Retorna as condições climáticas atuais de uma cidade que qualquer país que seja.
    Use esta ferramenta para saber se está chovendo, a temperatura
    e o clima geral de uma cidade específica dentro de um estado.
    """
    lat, lon = get_cordinates(cidade, uf, country)
    clima = get_weather_data(lat, lon)
    return clima



@tool
def get_previsao(cidade: str, uf: str, country: str) -> dict:
    """
    Retorna a PREVISÃO do tempo dos próximos dias (não o clima atual) de uma cidade.
    Use quando o usuário perguntar sobre viajar/passear em uma data futura,
    fim de semana, amanhã, ou "os próximos dias".
    """
    lat, lon = get_cordinates(cidade, uf, country)
    previsao = get_forecast_data(lat, lon)
    # Compacta para não estourar o contexto do modelo: janelas de 3h nas próximas ~24h
    itens = previsao.get("list", [])[:8]
    resumo = [
        {
            "data_hora": i.get("dt_txt"),
            "temp": i.get("main", {}).get("temp"),
            "condicao": (i.get("weather") or [{}])[0].get("description"),
        }
        for i in itens
    ]
    return {"cidade": cidade, "previsao": resumo}



@tool
def buscar_atracoes(cidade: str, uf: str, country: str) -> list:
    """
    Busca atrações turísticas REAIS de uma cidade (nome, categoria e, quando
    disponível, se está aberta). Use esta ferramenta para descobrir passeios
    reais em vez de sugerir de memória. NÃO invente atrações nem o status de
    aberto/fechado: baseie-se no retorno desta tool.
    """
    lat, lon = get_cordinates(cidade, uf, country)
    return get_attractions(lat, lon)
