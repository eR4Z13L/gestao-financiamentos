"""Gera desktop/assets/icone_app.ico - usado no .exe empacotado (ver .spec).

Icone provisorio (fundo azul arredondado + barras ascendentes, mesmo tom de
azul de destaque do tema claro) ate o projeto ter uma identidade visual
propria. So precisa do Pillow (nao e dependencia do app em si, so desta
ferramenta de build - "pip install pillow" antes de rodar, se precisar).

Rodar com: venv/Scripts/python.exe scripts/gerar_icone.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

DESTINO = Path(__file__).resolve().parent.parent / "desktop" / "assets" / "icone_app.ico"

AZUL = (47, 111, 237, 255)  # mesmo azul de destaque do tema claro (#2f6fed)
BRANCO = (255, 255, 255, 255)

_TAMANHOS = [16, 24, 32, 48, 64, 128, 256]


def _desenhar(tamanho: int) -> Image.Image:
    img = Image.new("RGBA", (tamanho, tamanho), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    raio = tamanho * 0.22
    d.rounded_rectangle([0, 0, tamanho - 1, tamanho - 1], radius=raio, fill=AZUL)

    # 3 barras ascendentes (mini-grafico de desempenho), centralizadas
    n_barras = 3
    largura_barra = tamanho * 0.14
    espaco = tamanho * 0.08
    alturas = [0.30, 0.48, 0.66]  # fracao da altura util de cada barra
    base_y = tamanho * 0.74
    topo_area = tamanho * 0.22

    largura_total = n_barras * largura_barra + (n_barras - 1) * espaco
    x = (tamanho - largura_total) / 2
    raio_barra = largura_barra * 0.28

    for altura_frac in alturas:
        altura_barra = (base_y - topo_area) * altura_frac / max(alturas)
        y0 = base_y - altura_barra
        d.rounded_rectangle([x, y0, x + largura_barra, base_y], radius=raio_barra, fill=BRANCO)
        x += largura_barra + espaco

    return img


def main() -> None:
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    imagens = [_desenhar(t) for t in _TAMANHOS]
    imagens[-1].save(DESTINO, format="ICO", sizes=[(t, t) for t in _TAMANHOS])
    print(f"ícone salvo em: {DESTINO}")


if __name__ == "__main__":
    main()
