# Fala, Lavoura!

**A roça que conversa com quem cuida dela.**

Global Solution 2026.2 · FIAP · *Generative AI and Advanced Nets* · Tema **CitizenTech**

| Integrante | RM |
|---|---|
| Claudio Alves de Carvalho Junior | 568565 |
| Gustavo Duarte | 567066 |
| Leonardo Pereira dos Santos | 567836 |

**Vídeo de demonstração:** https://youtu.be/Q1RkOQ9VM5Q · **Documentação técnica (PDF):** [docs/Fala_Lavoura_Documentacao.pdf](docs/Fala_Lavoura_Documentacao.pdf)

---

## A ideia

Quase 8 em cada 10 propriedades rurais do Brasil são de agricultura familiar, mas só uma pequena parte delas recebe assistência técnica. A informação até existe (Embrapa, Emater, previsão do tempo), só que chega espalhada, em linguagem difícil e quase sempre em texto longo.

O **Fala, Lavoura!** dá voz à plantação. O agricultor pergunta por texto, áudio ou foto, e quem responde é a própria lavoura, em primeira pessoa, com frases curtas e em áudio:

> *"Dona Maria, sou eu, o seu milho! Estou com 62 dias, exatamente na minha fase mais crítica. A boa notícia é que não precisa me regar esta semana, pois as chuvas previstas somam 36,1 mm..."*

Por trás dessa conversa existe um agente com RAG híbrido, clima ao vivo, cálculo de água pelo método FAO-56, guardrails e um verificador, o Fiscal da Roça, que confere cada resposta e manda os casos de risco para um técnico humano.

## O que torna o projeto diferente

| Ideia | Por que importa |
|---|---|
| **A lavoura fala em primeira pessoa** | Uma planta pedindo água é mais fácil de entender e lembrar do que um relatório. |
| **"A IA não faz conta, a IA conta a história"** | Litros, fase e chuva vêm de código testado e de uma API real. O modelo só narra, e isso corta a alucinação de números. |
| **Dicionário da Roça** | Traduz "fundo preto", "bicho comendo a folha" e "dinheiro do banco" para termos técnicos antes da busca. Subiu o acerto da busca de 66% para 82%. |
| **RAG híbrido** | Busca por palavras (BM25 feito por nós, funciona sem internet) e por significado (embeddings do Gemini), unidas por Reciprocal Rank Fusion. |
| **Fiscal da Roça e semáforo** | Um segundo modelo confere se cada afirmação tem fonte. Verde, amarelo e vermelho mostram o quanto confiar. |
| **"Não sei" vira pergunta para um humano** | Quando a base não cobre o assunto, o caso vai para a fila do técnico da Emater. |
| **Segurança que não depende do modelo** | Intoxicação dispara um protocolo fixo, sem IA. Pedidos de dose são detectados na entrada, e um filtro heurístico barra doses na saída. |
| **Foto não é diagnóstico** | O Gemini só descreve os sintomas; a conclusão vem das fichas técnicas. |
| **Carta da Semana** | A lavoura escreve um recado curto, pronto para o WhatsApp, com áudio. |

## Resultados em resumo

- **Busca:** acerto em primeiro lugar de 66% (BM25 puro) para 92% (híbrido), com 100% de acerto entre os três primeiros.
- **Contra o Gemini puro (13 cenários, uma rodada, juiz LLM às cegas):** 31 de 32 itens obrigatórios (97%) e nenhuma violação, contra 27 de 32 (84%) e 5 violações do baseline, entre elas uma dose de veneno calculada, um guia inventado de plantio de quinoa e uma explicação pseudocientífica sobre a lua.
- **Respostas** três vezes mais curtas e mais fáceis de ler.
- **Ressalvas da avaliação:** o placar de itens tem teto por cenário (sem ele, o juiz somaria 33 e 31), o juiz deu nota 5 em tudo ao nosso sistema, 6 das 26 avaliações usaram um juiz da mesma família do gerador e o baseline é um prompt de uma linha. Detalhes na seção 7.3 da documentação.
- **58 testes automatizados**, todos passando.

Detalhes, diagramas e limitações estão na [documentação técnica](docs/DOCUMENTACAO_TECNICA.md) e no [PDF](docs/Fala_Lavoura_Documentacao.pdf).

## Como rodar

Você vai precisar do Python 3.11 ou mais novo.

```bash
python -m venv .venv
```

Ative o ambiente com `.venv\Scripts\activate` no Windows ou `source .venv/bin/activate` no Linux e no Mac.

```bash
pip install -r requirements.txt
```

Copie o `.env.example` para `.env` e coloque sua chave gratuita do [Google AI Studio](https://aistudio.google.com/apikey) em `GOOGLE_API_KEY`.

```bash
python app.py
```

Depois é só abrir http://127.0.0.1:7860. Sem chave, o app abre no modo sem IA generativa (só busca e cálculos), o que também é útil para comparar.

> **Sobre a cota gratuita:** o plano gratuito do Gemini dá cerca de 20 requisições por dia para cada modelo, e cada pergunta usa umas 3. O app troca sozinho para um modelo reserva quando o principal fica sem cota ou sobrecarregado.

### Testes e avaliação

```bash
python -m pytest -q
```

```bash
python avaliacao/avaliar_recuperacao.py
```

```bash
python avaliacao/avaliar_geracao.py
```

Os relatórios ficam em `avaliacao/resultados/`. Para gerar o PDF da documentação:

```bash
python docs/gerar_pdf.py
```

## Estrutura

```
fala-lavoura/
├── app.py                      interface Gradio (conversa, painel da semana, fila do técnico)
├── falalavoura/
│   ├── agente.py               agente ReAct, Fiscal da Roça, semáforo e Carta da Semana
│   ├── conhecimento.py         RAG: divisão em trechos, BM25, embeddings, RRF e força da evidência
│   ├── agronomia.py            fases das culturas e balanço hídrico FAO-56
│   ├── clima.py                previsão real (Open-Meteo) e alertas
│   ├── guardrails.py           regras de entrada e saída e anonimização
│   ├── prompts.py              todos os prompts
│   ├── percepcao.py            foto para sintomas e áudio para texto (Gemini multimodal)
│   ├── voz.py                  texto para fala (gTTS)
│   ├── fila.py                 fila do técnico (humano no circuito)
│   ├── texto.py                normalização, stemmer leve e índice Flesch-PT
│   └── config.py
├── base_conhecimento/          11 fichas técnicas (68 trechos) e o Dicionário da Roça
├── avaliacao/                  perguntas, cenários, scripts e resultados
├── tests/                      58 testes automatizados
└── docs/                       documentação técnica, PDF e figuras
```

## Ligação com as outras entregas da Global Solution

- **PLN (Fábrica de Corpus):** gera, a partir de documentos oficiais do Pronaf, Garantia-Safra, CAF e ATER, o corpus para treinar um SLM local. Esse SLM é o próximo passo para o modo offline do Fala, Lavoura!; hoje, sem internet, já funcionam a busca BM25, os cálculos, os guardrails e o protocolo de emergência.
- **RPA (Mutirão):** o robô lê a fila do técnico gravada por este app (`dados/fila_tecnico.jsonl`), junta com as solicitações dos outros canais, prioriza e devolve o status de cada caso.

## Errata do vídeo

No vídeo dissemos que as respostas foram avaliadas por "um juiz de outra família de modelos, às
cegas". A avaliação foi às cegas, mas o juiz principal (Gemma 4) só avaliou 20 das 26 respostas;
nas outras 6 o juiz reserva foi o Gemini 3.5 Flash-Lite, da mesma família do gerador, e nos
cenários s09 a s12 cada lado foi julgado por um juiz diferente. O juiz também foi pouco
discriminante: deu nota 5 em tudo ao Fala, Lavoura!, inclusive no s13, em que a resposta cumpriu
1 de 2 itens. Os números do vídeo (97% contra 84%, 0 contra 5 violações) estão certos, mas valem
como indício, não como medida precisa. As ressalvas completas estão na seção 7.3 da documentação.

Texto para a descrição do vídeo:

> Errata: o juiz principal da avaliação foi o Gemma 4 (outra família), mas em 6 das 26 avaliações o
> juiz reserva foi o Gemini 3.5 Flash-Lite, da mesma família do gerador. O juiz deu nota 5 em tudo,
> o placar de itens tem teto por cenário e o baseline é um prompt de uma linha; as ressalvas estão
> na seção 7.3 da documentação. Após a gravação, o filtro de doses e a anonimização foram reforçados.

## Alterações após a gravação do vídeo (19/11/2026)

O vídeo mostra a versão anterior; o funcionamento da interface não mudou. Mudanças:

- `guardrails.verificar_saida` também barra dose por extenso ("meio copo", "duas colheres"), volume por hectare ou de calda e mais princípios ativos. A documentação agora chama o filtro de heurística, que é o que ele é.
- CPF, telefone e e-mail digitados são mascarados antes de a pergunta ir ao Gemini, e não só na fila do técnico.
- Segunda revisão: o filtro também barra unidade "tampa" e "xícara", contexto "dose"/"mata-mato" e uma lista curta de nomes comerciais (Engeo, Roundup...), e o CPF com espaços passou a ser mascarado.
- Terceira revisão: o protocolo de emergência agora dispara também com ingestão ("meu filho bebeu veneno", "tomou o mata-mato") e com produto no olho, mesmo sem sintoma; "quanto de mata-mato eu ponho" é marcado como pedido de dose; o filtro barra quantidade vaga ("um pouquinho de veneno") e emamectina.
- 29 testes novos (29 para 58), incluindo respostas de adubação e água que não podem ser barradas e frases como "tomei remédio para dor", que não podem disparar a emergência.
- Documentação: ressalvas da avaliação (teto do placar, juiz pouco discriminante, juízes diferentes em s09 a s12, baseline sem prompt de segurança), base de conhecimento sem validação de agrônomo como maior risco residual e a ligação com as GS de PLN e RPA.

> Projeto acadêmico. O Fala, Lavoura! não substitui o técnico de extensão rural nem o receituário agronômico.
