import requests

API_URL = "http://127.0.0.1:8000/recomendacao"

def main():
    estado = input("Em qual estado você quer passear? ").strip()
    if not estado:
        print("Nenhum estado informado. Encerrando.")
        return

    try:
        resp = requests.post(API_URL, json={"estado": estado})
        resp.raise_for_status()
        print(resp.json()["recomendacao"])
    except requests.exceptions.ConnectionError:
        print("Não consegui conectar à API. Ela está rodando? (uvicorn main:app)")
    except requests.exceptions.HTTPError as e:
        print(f"Erro na API: {e}")

if __name__ == "__main__":
    main()