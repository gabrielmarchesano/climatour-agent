# Case 2: Agente ClimaTour
Agente de IA de recomendação de passeios turísticos

## Pré-requisitos

- Python 3.10+
- Chaves de API: OpenWeatherMap e Groq
  
## Instalação

```bash
pip install -r requirements.txt

```
## Configuração
- Crie um arquivo .env na raiz do projeto (use .env.example como referência)
- Para ter acesso as API's necessárias utilize os links:
```link
https://console.groq.com/keys
https://openweathermap.org/api
```

## Execução
- Suba a API
```bash
uvicorn main:app --reload
```
- Execute o CLI em um novo terminal
```bash
python cli.py
```

### O agente irá perguntar o estado em que você se encontra, basta responder e aproveitar as recomendações =)
