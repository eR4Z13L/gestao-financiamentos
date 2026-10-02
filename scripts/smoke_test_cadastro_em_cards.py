"""Testa a peca de cadastro em cards (desktop/widgets/cadastro_em_cards.py) com cadastros FICTICIOS em memoria
(nenhuma planilha e lida ou gravada): os dois jeitos de editar (no lugar com 1 campo, para baixo com 2+), largura
fixa dos cards e quantos cabem por linha, clique simples sem efeito, duplo clique, Enter e Esc.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_cadastro_em_cards.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
from ambiente_de_teste import Mensagens
from desktop.theme import TEMA_ESCURO, build_stylesheet
from desktop.widgets.cadastro_em_cards import LARGURA_CARD, CadastroEmCards, Campo, DefinicaoDoCadastro, ItemDoCadastro


class ErroFicticio(Exception):
    pass


class CadastroFicticio:
    """Um "core" em memoria: guarda os itens e anota cada chamada."""

    def __init__(self, campos: list[Campo], nomes: list[str]):
        self.campos = campos
        self.itens = {n: {"nome": n, **{c.chave: "" for c in campos if c.chave != "nome"}, "ativo": True} for n in nomes}
        self.chamadas: list[tuple] = []

    def definicao(self) -> DefinicaoDoCadastro:
        def listar():
            return [ItemDoCadastro(n, n, f"detalhe de {n}", d["ativo"], {c.chave: d[c.chave] for c in self.campos})
                    for n, d in sorted(self.itens.items())]

        def adicionar(valores):
            self.chamadas.append(("adicionar", valores))
            if valores["nome"] in self.itens:
                raise ErroFicticio("já existe")
            self.itens[valores["nome"]] = {**valores, "ativo": True}
            return ""

        def salvar(chave, valores):
            self.chamadas.append(("salvar", chave, valores))
            dados = self.itens.pop(chave)
            self.itens[valores["nome"]] = {**dados, **valores}
            return ""

        def definir_ativo(chave, ativo):
            self.chamadas.append(("ativo", chave, ativo))
            self.itens[chave]["ativo"] = ativo
            return ""

        return DefinicaoDoCadastro("Itens", "item", "Cadastro fictício de teste.", self.campos, listar, adicionar, salvar,
                                   definir_ativo, None, (ErroFicticio,))


class JanelasSoltas(QObject):
    """Anota toda janela que aparece na tela fora as esperadas: um pedaco do card mostrado antes de ter dono
    pisca como uma janelinha solta (aconteceu de verdade, ao cadastrar um banco)."""

    def __init__(self, *esperadas):
        super().__init__()
        self.esperadas = esperadas
        self.vistas: list[str] = []

    def eventFilter(self, objeto, evento) -> bool:
        if evento.type() == QEvent.Type.Show and objeto.isWidgetType() and objeto.isWindow() and objeto not in self.esperadas:
            self.vistas.append(type(objeto).__name__)
        return False


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _mostrar(widget, largura: int) -> None:
    widget.resize(largura, 560)
    widget.show()
    for _ in range(3):
        QApplication.processEvents()


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet(TEMA_ESCURO))
    with Mensagens() as msgs:
        linha("1) Largura fixa: cabem tantos cards quanto a largura deixar, sem esticar")
        varios = CadastroFicticio([Campo("nome", "Nome", True)], [f"Item {i}" for i in range(7)])
        cad = CadastroEmCards(varios.definicao())
        soltas = JanelasSoltas(cad)
        app.installEventFilter(soltas)
        for largura, colunas in ((700, 2), (1100, 3), (1400, 4)):
            _mostrar(cad, largura)
            assert cad._colunas == colunas, (largura, cad._colunas)
            assert all(c.width() == LARGURA_CARD for c in cad.cards)
        print("OK: 700 px -> 2 colunas, 1100 -> 3, 1400 -> 4; todo card com a mesma largura.")

        card = cad.cards[0]
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(40, 10))
        assert cad._card_aberto() is None, "clique simples nao entra em edicao"
        QTest.mouseDClick(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(40, 10))
        aberto = cad._card_aberto()
        assert aberto is not None and aberto.no_lugar and aberto.titulo.isHidden() and aberto.etiqueta.isHidden()
        assert aberto.width() == LARGURA_CARD
        QTest.keyClick(aberto.campos["nome"], Qt.Key.Key_Escape)
        assert cad._card_aberto() is None and varios.chamadas == [], "Esc cancela sem gravar"
        cad.cards[0].botoes["editar"].click()
        caixa = cad._card_aberto().campos["nome"]
        caixa.setText("Item Zero")
        QTest.keyClick(caixa, Qt.Key.Key_Return)
        assert varios.chamadas == [("salvar", "Item 0", {"nome": "Item Zero"})] and cad._card_aberto() is None
        print("OK: 1 campo: clique simples não faz nada; duplo clique edita no lugar; Esc cancela; Enter salva.")
        cad.botao_novo.click()
        cad._card_aberto().campos["nome"].setText("Item Novo")
        cad._card_aberto().botoes["salvar"].click()
        assert soltas.vistas == [], f"apareceram janelas soltas na tela: {soltas.vistas}"
        print("OK: montar, editar e cadastrar não fazem nenhuma janelinha solta piscar na tela.")
        app.removeEventFilter(soltas)
        cad.close()

        linha("2) 2+ campos: o card abre para baixo, na mesma largura")
        campos = [Campo("nome", "Nome", True), Campo("fornecedor", "Fornecedor"), Campo("parcelas", "Parcelas")]
        grande = CadastroFicticio(campos, ["Alfa", "Beta", "Gama", "Delta"])
        cad = CadastroEmCards(grande.definicao())
        _mostrar(cad, 1100)
        altura_fechado = cad.cards[1].height()
        cad.cards[1].botoes["editar"].click()
        QApplication.processEvents()
        aberto = cad._card_aberto()
        assert not aberto.no_lugar and aberto._editor is not None and not aberto.titulo.isHidden()
        assert set(aberto.campos) == {"nome", "fornecedor", "parcelas"}
        assert aberto.width() == LARGURA_CARD and aberto.height() > altura_fechado, "abre so para baixo"
        assert cad._grade.getItemPosition(cad._grade.indexOf(aberto))[3] == 1, "nao ocupa a linha inteira"
        aberto.campos["fornecedor"].setText("Fornecedor Novo")
        aberto.botoes["salvar"].click()
        assert grande.chamadas[-1] == ("salvar", "Beta", {"nome": "Beta", "fornecedor": "Fornecedor Novo", "parcelas": ""})
        print("OK: o card abre para baixo com os 3 campos, mantém a largura e ocupa só a coluna dele.")

        cad.botao_novo.click()
        novo = cad._card_aberto()
        assert novo.item is None and cad.cards[0] is novo and novo.botoes["salvar"].text() == "Adicionar"
        novo.campos["nome"].setText("Alfa")
        novo.botoes["salvar"].click()
        assert msgs.ultima()[1] == "Não foi possível cadastrar" and cad._card_aberto() is novo, "erro: continua aberto"
        novo.campos["nome"].setText("Epsilon")
        novo.botoes["salvar"].click()
        assert "Epsilon" in grande.itens and cad._card_aberto() is None
        print("OK: '+ Novo' abre um card no início com 'Adicionar'; erro do core aparece e o card continua aberto.")

        gama = next(c for c in cad.cards if c.item and c.item.titulo == "Gama")
        assert set(gama.acoes) == {"ativo"} and gama.botoes["menu"].isVisibleTo(gama), "sem excluir na definicao: so Desativar"
        gama.acoes["ativo"].trigger()
        assert grande.chamadas[-1] == ("ativo", "Gama", False)
        assert next(c for c in cad.cards if c.item and c.item.titulo == "Gama").etiqueta.texto() == "Inativo"
        print("OK: o menu dos três pontinhos só mostra as ações que o cadastro tem; desativar muda a etiqueta.")
        cad.close()
    linha("TUDO OK")


if __name__ == "__main__":
    main()
