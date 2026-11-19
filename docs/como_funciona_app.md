### Como o Fala, Lavoura! funciona

1. **Você pergunta** por texto, áudio ou foto. O áudio é transcrito e a foto vira uma descrição de sintomas (o Gemini descreve, não diagnostica).
2. **Regras de segurança** checam a pergunta. Sinais de intoxicação disparam uma resposta de emergência fixa, sem passar pela IA.
3. **O agente** (Gemini com ferramentas) decide o que consultar:
   - **fichas técnicas** com busca híbrida (palavras + significado) e o *Dicionário da Roça*, que entende "fundo preto", "bicho comendo a folha", "dinheiro do banco"...
   - **clima real** dos próximos 7 dias (Open-Meteo);
   - **fase da lavoura** e **necessidade de água**, calculadas por código pelo método FAO-56. *A IA não faz conta: ela conta a história.*
4. **A lavoura responde** em primeira pessoa, com frases curtas e a fonte de cada recomendação.
5. **O Fiscal da Roça** (um segundo modelo) confere se tudo o que foi dito está nas fontes e acende o **semáforo**: verde (apoiado nas fichas), amarelo (confira com cuidado) ou vermelho (precisa de técnico).
6. Casos de risco, dúvidas que a base não cobre e pedidos de dose de agrotóxico viram uma **ficha para o técnico** da Emater.

### O que o app NÃO faz

- Não indica produto químico, dose nem mistura: isso exige **receituário agronômico**.
- Não dá diagnóstico definitivo por foto: só levanta suspeitas e ensina a confirmar no campo.
- Não substitui o técnico de extensão rural. Ele ajuda você a chegar mais preparado(a) nessa conversa.
- Os cálculos de água partem de premissas (solo com metade da água útil no início, sem sensor). Use como orientação, olhando a terra também.

### Privacidade

O app não pede nome completo, CPF nem telefone. A fila do técnico guarda só o município, a cultura e a pergunta, com dados pessoais mascarados. Fotos e áudios não são salvos pelo app.

<sub>Projeto acadêmico · Global Solution 2026.2 · FIAP · Generative AI and Advanced Nets</sub>
