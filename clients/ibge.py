import requests


url = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{UF}/municipios"

def get_municipios(uf: str) -> list:
    """
    Get a list of municipalities for a given state (UF) in Brazil using the IBGE API.

    :param uf: State abbreviation (UF)
    :return: List of municipalities
    """
    response = requests.get(url.format(UF=uf))

    if response.status_code == 200:
        return response.json()
    else:
        response.raise_for_status()

print(get_municipios("SP"))  # Example usage for the state of São Paulo (SP)
