"""Temas da aplicacao (escuro/claro).

As paletas ficam centralizadas aqui (em vez de espalhar cores hex pelas
telas) - se uma cor mudar, muda so num lugar. As duas paletas usam as mesmas
chaves de proposito, pra build_stylesheet() nao precisar saber qual tema
esta ativo.

O tema claro tem um bloco de CSS extra (so ele) com ajustes de contraste
entre camadas (fundo x sidebar x cards) e hierarquia de botoes/campos - o
tema escuro usa so o bloco base, sem nenhuma dessas mudancas.
"""

from __future__ import annotations

TEMA_ESCURO = "escuro"
TEMA_CLARO = "claro"

PALETA_ESCURA = {
    "bg": "#0e1117",
    "bg_sidebar": "#171a21",
    "bg_secundario": "#171a21",
    "bg_card": "#1c1f2b",
    "borda": "#2b2f3a",
    "texto": "#fafafa",
    "texto_secundario": "#9aa0ac",
    "destaque": "#4f8bf9",
    "destaque_hover": "#3f74d6",
    "sucesso": "#2ecc71",
    "erro": "#ff4b4b",
}

PALETA_CLARA = {
    # mais saturado que antes (era quase branco - #f5f6f8 - e some visualmente
    # contra os cards brancos)
    "bg": "#e4e8ee",
    # sidebar com tom proprio, mais escuro que o fundo principal - ancora a
    # navegacao visualmente em vez de se misturar com o conteudo
    "bg_sidebar": "#d7dee7",
    # usado na zebra da tabela e no cabecalho - claro o bastante pra nao
    # competir com o card branco, mas distinto do fundo principal
    "bg_secundario": "#f3f5f7",
    "bg_card": "#ffffff",
    "borda": "#c9d1db",
    "texto": "#1a1d23",
    "texto_secundario": "#5f6672",
    "destaque": "#2f6fed",
    "destaque_hover": "#2558c4",
    "sucesso": "#1e9e5a",
    "erro": "#d63939",
}

PALETAS = {TEMA_ESCURO: PALETA_ESCURA, TEMA_CLARO: PALETA_CLARA}


def build_stylesheet(tema: str = TEMA_ESCURO) -> str:
    p = PALETAS.get(tema, PALETA_ESCURA)
    base = f"""
    QMainWindow, QWidget {{
        background-color: {p['bg']};
        color: {p['texto']};
        font-family: "Segoe UI", sans-serif;
        font-size: 13px;
    }}

    QFrame[role="sidebar"] {{
        background-color: {p['bg_sidebar']};
        border: none;
        border-right: 1px solid {p['borda']};
    }}

    QListWidget {{
        background-color: transparent;
        border: none;
        padding: 6px 10px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 11px 14px;
        border-radius: 8px;
        margin: 2px 0px;
        color: {p['texto_secundario']};
    }}
    QListWidget[recolhido="true"]::item {{
        padding: 11px 0px;
    }}
    QListWidget::item:selected {{
        background-color: {p['destaque']};
        color: white;
        font-weight: 600;
    }}
    QListWidget::item:hover:!selected {{
        background-color: {p['bg_card']};
        color: {p['texto']};
    }}

    QLabel[role="titulo_app"] {{
        font-size: 15px;
        font-weight: 700;
        color: {p['texto']};
    }}

    QPushButton[role="botao_icone"] {{
        background-color: transparent;
        border: none;
        border-radius: 8px;
        font-size: 15px;
        padding: 6px;
    }}
    QPushButton[role="botao_icone"]:hover {{
        background-color: {p['bg_card']};
        border: none;
    }}
    QPushButton[role="botao_icone"]:pressed {{
        background-color: {p['borda']};
    }}

    QPushButton[role="botao_tema"] {{
        background-color: transparent;
        border: none;
        border-top: 1px solid {p['borda']};
        border-radius: 0px;
        text-align: left;
        padding: 16px 18px;
        color: {p['texto_secundario']};
        font-size: 13px;
    }}
    QPushButton[role="botao_tema"]:hover {{
        background-color: {p['bg_card']};
        color: {p['texto']};
        border-top: 1px solid {p['borda']};
    }}
    QPushButton[role="botao_tema"]:pressed {{
        background-color: {p['borda']};
        border-top: 1px solid {p['borda']};
    }}

    QLabel[role="titulo"] {{
        font-size: 22px;
        font-weight: 600;
    }}
    QLabel[role="subtitulo"] {{
        font-size: 15px;
        font-weight: 600;
    }}
    QLabel[role="secundario"] {{
        color: {p['texto_secundario']};
    }}
    QLabel[role="valor_metrica"] {{
        font-size: 26px;
        font-weight: 700;
    }}

    /* par legenda/valor da ficha do cliente (CPF, Celular, Nascimento...) -
       cores iguais nos dois temas; o tema claro reforca a diferenca de
       tamanho/peso no bloco especifico la embaixo */
    QLabel[role="campo_rotulo"] {{
        color: {p['texto_secundario']};
    }}
    QLabel[role="campo_valor"] {{
        color: {p['texto']};
    }}

    QFrame[role="card"] {{
        background-color: {p['bg_card']};
        border: 1px solid {p['borda']};
        border-radius: 8px;
    }}

    QLineEdit {{
        background-color: {p['bg_card']};
        border: 1px solid {p['borda']};
        border-radius: 6px;
        padding: 6px 8px;
        color: {p['texto']};
    }}
    QLineEdit:focus {{
        border: 1px solid {p['destaque']};
    }}
    QLineEdit[invalido="true"] {{
        border: 1px solid {p['erro']};
    }}

    QComboBox {{
        background-color: {p['bg_card']};
        border: 1px solid {p['borda']};
        border-radius: 6px;
        padding: 5px 8px;
        color: {p['texto']};
    }}
    QComboBox:focus {{
        border: 1px solid {p['destaque']};
    }}
    QComboBox QAbstractItemView {{
        background-color: {p['bg_card']};
        color: {p['texto']};
        selection-background-color: {p['destaque']};
        selection-color: white;
        outline: none;
    }}

    QTableView {{
        background-color: {p['bg_card']};
        alternate-background-color: {p['bg_secundario']};
        gridline-color: {p['borda']};
        border: 1px solid {p['borda']};
        border-radius: 6px;
        color: {p['texto']};
        selection-background-color: {p['destaque']};
        selection-color: white;
    }}
    QHeaderView::section {{
        background-color: {p['bg_secundario']};
        color: {p['texto_secundario']};
        padding: 6px;
        border: none;
        border-bottom: 1px solid {p['borda']};
        font-weight: 600;
    }}

    QPushButton {{
        background-color: {p['bg_card']};
        border: 1px solid {p['borda']};
        border-radius: 6px;
        padding: 6px 14px;
        color: {p['texto']};
    }}
    QPushButton:hover {{
        border: 1px solid {p['destaque']};
    }}
    QPushButton:pressed {{
        background-color: {p['destaque']};
    }}

    /* acao primaria (cadastrar, editar, atualizar, ...) - uma unica cor de
       destaque em todo o app, em vez de azul/roxo/laranja misturados */
    QPushButton[role="botao_primario"] {{
        background-color: transparent;
        border: 1px solid {p['destaque']};
        border-radius: 6px;
        padding: 6px 14px;
        color: {p['destaque']};
        font-weight: 600;
    }}
    QPushButton[role="botao_primario"]:hover {{
        background-color: {p['destaque']};
        color: white;
    }}
    QPushButton[role="botao_primario"]:pressed {{
        background-color: {p['destaque_hover']};
        border: 1px solid {p['destaque_hover']};
        color: white;
    }}

    /* acao destrutiva (excluir) - vermelho, pra nunca passar despercebida */
    QPushButton[role="botao_perigo"] {{
        background-color: transparent;
        border: 1px solid {p['erro']};
        border-radius: 6px;
        padding: 6px 14px;
        color: {p['erro']};
        font-weight: 600;
    }}
    QPushButton[role="botao_perigo"]:hover {{
        background-color: {p['erro']};
        color: white;
    }}
    QPushButton[role="botao_perigo"]:pressed {{
        background-color: {p['erro']};
        border: 1px solid {p['erro']};
        color: white;
    }}

    QScrollBar:vertical {{
        background: {p['bg']};
        width: 10px;
    }}
    QScrollBar::handle:vertical {{
        background: {p['borda']};
        border-radius: 5px;
        min-height: 20px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        height: 0px;
    }}
    """

    if tema != TEMA_CLARO:
        return base

    # ---- daqui pra baixo, SO tema claro - o escuro nunca ve isso ----------
    extras_tema_claro = f"""
    /* botao primario vira preenchido (nao so contorno) no claro - fica mais
       forte que o "Excluir" (que continua so contorno vermelho) */
    QPushButton[role="botao_primario"] {{
        background-color: {p['destaque']};
        color: white;
    }}
    QPushButton[role="botao_primario"]:hover {{
        background-color: {p['destaque_hover']};
        border: 1px solid {p['destaque_hover']};
        color: white;
    }}
    QPushButton[role="botao_primario"]:pressed {{
        background-color: {p['destaque_hover']};
        border: 1px solid {p['destaque_hover']};
        color: white;
    }}

    /* rotulo menor/apagado, valor maior/em negrito - o dado se destaca da
       etiqueta dele na ficha do cliente */
    QLabel[role="campo_rotulo"] {{
        font-size: 11px;
    }}
    QLabel[role="campo_valor"] {{
        font-size: 14px;
        font-weight: 600;
    }}
    """
    return base + extras_tema_claro
