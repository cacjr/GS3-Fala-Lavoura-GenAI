"""Gera docs/Fala_Lavoura_Documentacao.pdf a partir do DOCUMENTACAO_TECNICA.md.

Converte o Markdown em HTML com visual de relatório acadêmico (capa, sumário,
seções em página nova, legendas de figura e numeração de páginas) e imprime em
PDF com o Chrome ou o Edge em modo headless.

Rodar:  python docs/gerar_pdf.py
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

PASTA = Path(__file__).resolve().parent
MD = PASTA / "DOCUMENTACAO_TECNICA.md"
HTML = PASTA / "documentacao.html"
PDF = PASTA / "Fala_Lavoura_Documentacao.pdf"


CAPA = """
<section class="capa">
  <div class="instituicao">
    FIAP · Faculdade de Informática e Administração Paulista<br>
    Global Solution 2026.2 · Generative AI and Advanced Nets
  </div>
  <div class="titulo">
    <p class="rotulo">Documentação técnica</p>
    <h1>Fala, Lavoura!</h1>
    <p class="sub">A roça que conversa com quem cuida dela</p>
    <p class="resumo">Agente de IA generativa com RAG híbrido, ferramentas agronômicas e verificação
    de respostas para apoiar a agricultura familiar. Tema CitizenTech.</p>
  </div>
  <div class="autores">
    <p class="rotulo">Integrantes</p>
    <table>
      <tr><td>Claudio Alves de Carvalho Junior</td><td>RM 568565</td></tr>
      <tr><td>Gustavo Duarte</td><td>RM 567066</td></tr>
      <tr><td>Leonardo Pereira dos Santos</td><td>RM 567836</td></tr>
    </table>
  </div>
  <div class="local">São Paulo · Novembro de 2026</div>
</section>
"""

CSS = """
@page { size: A4; margin: 24mm 22mm 22mm 22mm;
  @bottom-right { content: counter(page); font: 9pt 'Inter', sans-serif; color: #777; }
  @bottom-left { content: "Fala, Lavoura! · Documentação técnica"; font: 8.5pt 'Inter', sans-serif; color: #999; } }
@page :first { margin: 0; @bottom-right { content: none; } @bottom-left { content: none; } }

:root { --tinta: #1c1c1a; --cinza: #5f5f5a; --linha: #d8d6cf; --destaque: #2f5d3a; }
html { font-family: 'Source Serif 4', Georgia, serif; font-size: 10.6pt; line-height: 1.58; color: var(--tinta); }
body { margin: 0; }
p { margin: 0 0 9px; text-align: justify; hyphens: auto; }
a { color: inherit; text-decoration: none; }

h2 { font-family: 'Inter', sans-serif; font-weight: 600; font-size: 19pt; letter-spacing: -0.3px;
     margin: 0 0 18px; padding-top: 4px; break-before: page; color: var(--tinta); }
h2 .num { color: var(--destaque); font-weight: 500; margin-right: 10px; }
h2::after { content: ""; display: block; width: 42px; border-bottom: 2px solid var(--destaque); margin-top: 10px; }
h3 { font-family: 'Inter', sans-serif; font-weight: 600; font-size: 11.5pt; margin: 22px 0 8px; break-after: avoid; }
h4 { font-family: 'Inter', sans-serif; font-weight: 600; font-size: 9pt; text-transform: uppercase;
     letter-spacing: 0.8px; color: var(--cinza); margin: 18px 0 6px; break-after: avoid; }

ul, ol { margin: 0 0 10px; padding-left: 20px; }
li { margin-bottom: 4px; }

table { width: 100%; border-collapse: collapse; margin: 12px 0 16px; break-inside: avoid;
        font-family: 'Inter', sans-serif; font-size: 8.4pt; line-height: 1.45;
        border-top: 1.4px solid var(--tinta); border-bottom: 1.4px solid var(--tinta); }
th { text-align: left; font-weight: 600; padding: 6px 8px; border-bottom: 0.8px solid var(--tinta); }
td { padding: 5px 8px; vertical-align: top; border-bottom: 0.5px solid var(--linha); }
tr:last-child td { border-bottom: none; }

blockquote { margin: 14px 0; padding: 2px 0 2px 16px; border-left: 2px solid var(--destaque); color: #3d3d39; }
blockquote p { margin: 0; }
code { font-family: 'JetBrains Mono', Consolas, monospace; font-size: 8.4pt; background: #f2f1ec; padding: 0 3px; border-radius: 2px; }
pre { font-size: 8pt; background: #f6f5f0; padding: 10px; white-space: pre-wrap; }
hr { display: none; }

figure { margin: 16px 0 18px; break-inside: avoid; text-align: center; }
figure pre.mermaid { background: none; padding: 0; }
figure.svg svg { width: 100%; height: auto; }
figcaption { font-family: 'Inter', sans-serif; font-size: 8.4pt; color: var(--cinza); margin-top: 8px; text-align: left; }
figcaption b { color: var(--tinta); font-weight: 600; }

.sumario h2 { break-before: auto; }
.sumario ol { list-style: none; padding: 0; font-family: 'Inter', sans-serif; font-size: 10pt; }
.sumario li { padding: 7px 0; border-bottom: 0.5px solid var(--linha); margin: 0; }
.sumario li span { color: var(--destaque); display: inline-block; width: 28px; }

.capa { height: 297mm; box-sizing: border-box; padding: 30mm 26mm 26mm; display: flex; flex-direction: column;
        justify-content: space-between; break-after: page; border-left: 10mm solid var(--destaque); }
.capa .instituicao { font-family: 'Inter', sans-serif; font-size: 9.5pt; line-height: 1.6; color: var(--cinza); }
.capa .rotulo { font-family: 'Inter', sans-serif; font-size: 8.5pt; text-transform: uppercase; letter-spacing: 1.6px;
                color: var(--destaque); margin: 0 0 10px; font-weight: 600; text-align: left; }
.capa h1 { font-family: 'Source Serif 4', Georgia, serif; font-weight: 600; font-size: 46pt; line-height: 1.05;
           letter-spacing: -1px; margin: 0 0 12px; color: var(--tinta); }
.capa .sub { font-size: 16pt; font-style: italic; color: #3d3d39; margin: 0 0 26px; text-align: left; }
.capa .resumo { font-size: 10.5pt; color: var(--cinza); max-width: 120mm; text-align: left; }
.capa table { width: auto; border: none; font-size: 10.5pt; margin: 0; }
.capa td { border: none; padding: 3px 28px 3px 0; }
.capa td:last-child { color: var(--cinza); }
.capa .local { font-family: 'Inter', sans-serif; font-size: 9.5pt; color: var(--cinza); }
"""

MERMAID_INIT = """
mermaid.initialize({startOnLoad: true, theme: 'base', flowchart: {useMaxWidth: true, curve: 'basis'},
  themeVariables: {fontFamily: 'Inter, sans-serif', fontSize: '15px', primaryColor: '#ffffff',
    primaryBorderColor: '#4a4a46', primaryTextColor: '#1c1c1a', lineColor: '#8a8a84',
    secondaryColor: '#f3f2ed', tertiaryColor: '#f7f7f4', clusterBkg: '#f7f7f4', clusterBorder: '#d8d6cf',
    edgeLabelBackground: '#ffffff'}});
"""


def converter():
    texto = MD.read_text(encoding="utf-8")
    texto = texto[texto.index("## Sumário"):]  # a capa vem do HTML acima

    blocos = []

    def guardar(m):
        blocos.append(m.group(1))
        return f"MERMAIDBLOCO{len(blocos) - 1}FIM"

    texto = re.sub(r"```mermaid\n(.*?)```", guardar, texto, flags=re.DOTALL)
    corpo = markdown.markdown(texto, extensions=["tables", "fenced_code", "toc", "sane_lists"])

    for i, b in enumerate(blocos):
        legenda = "Fluxo de uma pergunta, da entrada do agricultor até a resposta e o encaminhamento ao técnico."
        corpo = corpo.replace(f"<p>MERMAIDBLOCO{i}FIM</p>",
                              f'<figure><pre class="mermaid">{b}</pre><figcaption>FIGCAP{legenda}</figcaption></figure>')

    # Imagens SVG desenhadas à mão (docs/figuras) entram embutidas, com legenda tirada do texto alternativo
    def imagem(m):
        alt, src = m.group(1), m.group(2)
        svg = (PASTA / src).read_text(encoding="utf-8")
        return f'<figure class="svg">{svg}<figcaption>FIGCAP{alt}</figcaption></figure>'

    corpo = re.sub(r'<p><img alt="([^"]*)" src="([^"]+\.svg)"\s*/?></p>', imagem, corpo)

    # Numeração das figuras na ordem em que aparecem
    contador = iter(range(1, 100))
    corpo = re.sub(r"FIGCAP", lambda _: f"<b>Figura {next(contador)}.</b> ", corpo)

    # Sumário com a mesma numeração dos títulos
    def sumario(m):
        itens = re.findall(r"<li>(.*?)</li>", m.group(1), re.S)
        linhas = "".join(f"<li><span>{n}</span>{re.sub(r'<.*?>', '', item)}</li>" for n, item in enumerate(itens, 1))
        return f'<section class="sumario"><h2>Sumário</h2><ol>{linhas}</ol></section>'

    corpo = re.sub(r'<h2 id="sumario">Sumário</h2>\s*<ol>(.*?)</ol>', sumario, corpo, count=1, flags=re.S)
    # "1. Antes de tudo" vira número destacado + título
    corpo = re.sub(r'<h2 id="([^"]+)">(\d+)\. ', r'<h2 id="\1"><span class="num">\2</span>', corpo)

    html = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Fala, Lavoura! Documentação técnica</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&family=JetBrains+Mono&display=swap" rel="stylesheet">
<style>{CSS}</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<script>{MERMAID_INIT}</script>
</head><body>{CAPA}{corpo}</body></html>"""
    HTML.write_text(html, encoding="utf-8")


def imprimir():
    navegadores = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        shutil.which("chromium") or "", shutil.which("google-chrome") or "",
    ]
    nav = next((n for n in navegadores if n and Path(n).exists()), None)
    if not nav:
        sys.exit(f"Abra {HTML} no navegador e use Imprimir > Salvar como PDF.")
    # Caminho temporário curto + perfil isolado: o Windows e o navegador aberto atrapalham caminhos longos.
    tmp = Path(tempfile.mkdtemp(prefix="fala_pdf_"))
    html_tmp, pdf_tmp = tmp / "doc.html", tmp / "doc.pdf"
    shutil.copy(HTML, html_tmp)
    subprocess.run([nav, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--user-data-dir={tmp / 'perfil'}", "--virtual-time-budget=20000",
                    f"--print-to-pdf={pdf_tmp}", html_tmp.as_uri()], check=True, capture_output=True)
    if not pdf_tmp.exists():
        sys.exit(f"Não consegui gerar o PDF. Abra {HTML} no navegador e use Imprimir > Salvar como PDF.")
    shutil.copy(pdf_tmp, PDF)
    print(f"PDF gerado: {PDF}")


if __name__ == "__main__":
    converter()
    imprimir()
