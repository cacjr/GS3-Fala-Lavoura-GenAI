# Avaliação da recuperação

38 perguntas dentro do escopo + 4 fora do escopo, escritas no jeito de falar do agricultor. Base com 68 trechos. Modelo de embedding: `gemini-embedding-001`.

| Configuração | Hit@1 | Hit@3 | MRR | Fora do escopo detectado | 'Não sei' indevido (dentro do escopo) |
|---|---|---|---|---|---|
| A) BM25 puro | 0.658 | 0.868 | 0.765 | 4/4 | 3/38 |
| B) BM25 + dicionário | 0.816 | 0.947 | 0.877 | 4/4 | 0/38 |
| C) BM25 + dicionário + cultura | 0.816 | 0.947 | 0.887 | 4/4 | 0/38 |
| D) Embeddings + dicionário + cultura | 0.921 | 1.0 | 0.961 | 4/4 | 0/38 |
| E) Híbrido RRF + dicionário + cultura | 0.921 | 1.0 | 0.952 | 4/4 | 0/38 |

## Erros da configuração E) Híbrido RRF + dicionário + cultura

- “a raiz da mandioca apodreceu depois de muita chuva”: correto na posição 3 · top3 ['mandioca#colheita', 'mandioca#plantio-e-manivas', 'mandioca#agua-e-tolerancia-a-seca']
- “as folhas do tomate ficaram pretas e moles de um dia pro outro com essa garoa fria”: correto na posição 3 · top3 ['tomate#pinta-preta', 'tomate#irrigacao-regular', 'tomate#requeima']
- “o tomate tá rachando”: correto na posição 2 · top3 ['tomate#podridao-apical-fundo-preto', 'tomate#irrigacao-regular', 'tomate#requeima']