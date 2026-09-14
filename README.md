# Case 2: Agente ClimaTour
Agente de IA de recomendação de passeios turísticos  
Modelo utilizado: [openai/gpt-oss-120b](https://console.groq.com/docs/model/openai/gpt-oss-120b)

## Você pode testá-lo em:
https://climatour-agent.streamlit.app/

---

## Ou rodá-lo na sua própria máquina

### Pré-requisitos
- Python 3.10+
- Chaves de API gratuitas: [OpenWeatherMap](https://openweathermap.org/api) e [Groq](https://console.groq.com/keys). OBS: Você pode utilizar outro LLM que desejar, basta ter acesso à uma API_KEY
  
### Instalação
1. Certifique-se de ter o Python instalado.
2. Vá até a pasta raiz do projeto, e nele crie e ative um ambiente virtual:

   ```bash
   # Navegar até a pasta do projeto
   git clone https://github.com/gabrielmarchesano/climatour-agent.git
   cd climatour-agent
   
   # Criar o ambiente virtual
   python -m venv .venv

   # Ativar no Windows:
   .venv\Scripts\activate
   # (Se usar Linux/Mac: source .venv/bin/activate)

3. Com o ambiente virtual ativado instale as dependências

   ```bash
   pip install -r requirements.txt
   
### Configuração
- Crie um arquivo .env na raiz do projeto (use .env.example como referência) para adicionar suas chaves de acesso às API's (certifique-se de não expor elas)

  ```snippet
  GROQ_API_KEY="sua_chave_groq_aqui"
  OPENWEATHER_API_KEY="sua_chave_openweather_aqui"
  <MODEL>_API_KEY = "sua_chave_qualquermodelo_aqui"

### Execução
- Execute o streamlit no seu terminal na raiz do projeto
```bash
streamlit run app.py
```

---

## Observações e possíveis melhorias futuras
- Ausência de Memória de Contexto: O agente não retém o histórico das interações (stateless). Implementar memória permitiria perguntas de acompanhamento sobre as recomendações dadas.
- Feedback do usuário: O sistema não coleta a avaliação do usuário. Talvez adicionar mecanismos de adesão ou não a determinado passeio poderia ajudaria a medir a eficácia e a refinar o comportamento do modelo.

