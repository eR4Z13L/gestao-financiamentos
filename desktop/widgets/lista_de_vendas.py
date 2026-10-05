"""A lista de cards de venda, a mesma na tela Vendas e na Ficha de Cliente.

Os cards ficam em colunas que encaixam (desktop/widgets/colunas_que_encaixam.py, a mesma peca da lista de propostas);
esta lista cuida de qual esta ABERTO (um por vez: ele so cresce para baixo, na propria coluna), do formulario da
proposta dentro dele e de nunca descartar algo digitado sem perguntar. Quem mostra a lista decide QUAIS vendas
aparecem (busca, filtros, o cliente da ficha) e rele depois de gravar: a lista avisa pelo sinal `gravou`.
"""

from __future__ import annotations

from collections import Counter
from typing import Callable

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QScrollArea, QWidget

from core import sessao as sessao_mod
from core import vendas as vendas_mod
from desktop.dialogs.venda_dialog import VendaDialog
from desktop.widgets.card_da_venda import LARGURA_CARD, NOVA, CardDaVenda, ControleDasVendas, proposta_por_id
from desktop.widgets.colunas_que_encaixam import ListaEmColunas

SEGUNDOS_DO_AVISO = 8

_FRASE_STATUS = {  # (singular, plural) nas contagens
    vendas_mod.VENDA_AGUARDANDO: ("aguardando bancos", "aguardando bancos"),
    vendas_mod.VENDA_EM_ANDAMENTO: ("em andamento", "em andamento"),
    vendas_mod.VENDA_EFETIVADA: ("efetivada", "efetivadas"),
    vendas_mod.VENDA_NAO_EFETIVADA: ("não efetivada", "não efetivadas"),
    vendas_mod.VENDA_PERDIDA: ("perdida", "perdidas"),
}


def resumo_por_status(vendas: list[vendas_mod.ResumoDaVenda]) -> str:
    contagem = Counter(v.status for v in vendas)
    partes = []
    for status in vendas_mod.STATUS_DA_VENDA:
        if contagem.get(status):
            singular, plural = _FRASE_STATUS[status]
            partes.append(f"{contagem[status]} {singular if contagem[status] == 1 else plural}")
    return " · ".join(partes)


class FaixaDeAviso(QFrame):
    """"Santander: "Em Análise" → "Aprovado"." - o que acabou de mudar; some sozinha (desfazer = a setinha ↩)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "chip_filtro")
        linha = QHBoxLayout(self)
        linha.setContentsMargins(12, 6, 8, 6)
        self.texto = QLabel("", self)
        self.texto.setWordWrap(True)
        linha.addWidget(self.texto, stretch=1)
        self.setVisible(False)
        self._relogio = QTimer(self)
        self._relogio.setSingleShot(True)
        self._relogio.timeout.connect(lambda: self.setVisible(False))

    def avisar(self, texto: str) -> None:
        if not texto:
            return
        self.texto.setText(texto)
        self.setVisible(True)
        self._relogio.start(SEGUNDOS_DO_AVISO * 1000)


class ListaDeVendas(ListaEmColunas):
    gravou = Signal(str)  # gravou algo (o aviso a mostrar, "" = nenhum): quem mostra a lista rele as vendas
    ficha_pedida = Signal(str)  # cpf

    def __init__(self, rolagem: QScrollArea, parent: QWidget | None = None, *, com_ficha: bool = True,
                 uma_coluna: bool = False):
        """`rolagem`: quem rola a lista (a da tela). `com_ficha`: o "Abrir a ficha" do card aberto (na propria ficha
        nao faz sentido). `uma_coluna`: todo card na largura toda (a Ficha)."""
        super().__init__(rolagem, parent, largura_card=LARGURA_CARD, uma_coluna=uma_coluna)
        self._com_ficha = com_ficha
        self.aberta: str | None = None  # o ID_VENDA do card aberto
        self.editando: str | None = None  # no card aberto: o ID_PROPOSTA no formulario, NOVA, ou None
        self.antes_de_editar: Callable[[], bool] | None = None  # False: nao abre o formulario (ver abrir_venda)
        self.controle = ControleDasVendas(self, self.gravou.emit)

    # -- vendas -------------------------------------------------------------------------------------

    def definir_vendas(self, vendas: list[vendas_mod.ResumoDaVenda], *, texto_vazio: str = "",
                       voltar_ao_inicio: bool = False) -> None:
        """As vendas a mostrar, na ordem. `voltar_ao_inicio`: outra lista (busca, filtro, outro cliente) - volta
        a primeira pagina e nao devolve a rolagem; senao (releu depois de gravar) tudo fica onde estava."""
        if self.aberta not in {v.id for v in vendas}:
            self.aberta, self.editando = None, None
        self._definir_itens(vendas, texto_vazio, voltar_ao_inicio)

    def _chave(self, venda: vendas_mod.ResumoDaVenda) -> str:
        return venda.id

    def _posicao_que_precisa_aparecer(self) -> int | None:
        """O card aberto nunca fica alem da pagina carregada (o "Ver na venda →" de Todas as Propostas): ele aparece."""
        return next((i for i, v in enumerate(self._itens) if v.id == self.aberta), None) if self.aberta else None

    def _criar_card(self, venda: vendas_mod.ResumoDaVenda) -> CardDaVenda:
        card = CardDaVenda(venda, self, aberto=venda.id == self.aberta)
        self.controle.conectar(card)
        card.abrir_pedido.connect(self.abrir_venda)
        card.fechar_pedido.connect(lambda _v: self.fechar_venda())
        card.proposta_pedida.connect(self.editar_proposta)
        card.edicao_da_venda_pedida.connect(self.editar_venda)
        card.ficha_pedida.connect(self.ficha_pedida)
        if card.abrir_ficha is not None and not self._com_ficha:
            card.abrir_ficha.hide()
        if card.aberto and self.editando is not None:
            self._por_formulario(card)
        return card

    def _formulario_aberto(self) -> tuple[str, QWidget] | None:
        card = self.card_aberto()
        if card is None or card.formulario is None or self.editando is None:
            return None
        return f"{card.venda.id}|{self.editando}", card.formulario

    def venda_por_id(self, id_venda: str) -> vendas_mod.ResumoDaVenda | None:
        return next((v for v in self._itens if v.id == id_venda), None)

    # -- card aberto e formulario -------------------------------------------------------------------

    def card_aberto(self) -> CardDaVenda | None:
        return next((c for c in self.cards if c.aberto), None)

    def tem_edicao_pendente(self) -> bool:
        card = self.card_aberto()
        return card is not None and card.tem_alteracoes()

    def pode_descartar(self) -> bool:
        """Ha algo digitado no formulario aberto? Pergunta antes de descartar."""
        if not self.tem_edicao_pendente():
            return True
        resposta = QMessageBox.question(
            self, "Alterações não salvas", "Há uma proposta com alterações que ainda não foram salvas. Descartar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        return resposta == QMessageBox.StandardButton.Yes

    def descartar(self) -> None:
        """Fecha o formulario sem perguntar (quem chama ja perguntou ou avisou)."""
        if self.editando is not None or self.tem_edicao_pendente():
            self.editando = None
            self._montar()

    def liberar(self) -> bool:
        """Fecha o formulario (o card continua aberto), perguntando antes de descartar o digitado. False = a pessoa
        preferiu continuar editando (quem chamou nao segue)."""
        if self.editando is None:
            return True
        if not self.pode_descartar():
            return False
        self.editando = None
        self._montar()
        return True

    def abrir_venda(self, venda: vendas_mod.ResumoDaVenda, editando: str | None = None) -> bool:
        if venda.id == self.aberta and editando == self.editando:
            return True
        if not self.pode_descartar():
            return False
        # na Ficha ha outro formulario (o das propostas de antes das vendas): um por vez na tela
        if editando is not None and self.antes_de_editar is not None and not self.antes_de_editar():
            return False
        self.aberta, self.editando = venda.id, editando
        self._montar()
        self.rolar_ate_o_aberto()
        return True

    def rolar_ate_o_aberto(self) -> None:
        self.rolar_ate(self.card_aberto())

    def fechar_venda(self) -> bool:
        if not self.pode_descartar():
            return False
        self.aberta, self.editando = None, None
        self._montar()
        return True

    def editar_proposta(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda | None) -> bool:
        """O ✎ (ou dois cliques num banco, ou "+ Adicionar proposta"): abre o card, se preciso, com o formulario."""
        return self.abrir_venda(venda, NOVA if proposta is None else proposta.id)

    def _por_formulario(self, card: CardDaVenda) -> None:
        proposta = proposta_por_id(card.venda, self.editando)
        ao_excluir = (lambda: self._excluir(card.venda, proposta)) if proposta is not None else None  # noqa: E731
        guardado = self._formulario_guardado(f"{card.venda.id}|{self.editando}")
        if guardado is not None:  # o mesmo da montagem anterior, com o que ja foi digitado
            card.mostrar_formulario(self.editando, guardado, ao_excluir)
            return
        try:
            formulario = self.controle.criar_formulario(card.venda, self.editando)
        except Exception as exc:  # nunca falhar em silencio (ex.: a proposta sumiu entre a leitura e o clique)
            QMessageBox.warning(self, "Não foi possível abrir a proposta", f"{type(exc).__name__}: {exc}")
            self.editando = None
            return
        formulario.gravada.connect(self._ao_gravar_formulario)
        formulario.cancelada.connect(self._ao_cancelar_formulario)
        card.mostrar_formulario(self.editando, formulario, ao_excluir)
        QTimer.singleShot(0, formulario.dar_foco_inicial)

    def _ao_gravar_formulario(self) -> None:
        self.editando = None
        QTimer.singleShot(0, lambda: self.gravou.emit("Proposta gravada."))  # fora do sinal do formulario

    def _ao_cancelar_formulario(self) -> None:
        self.editando = None
        QTimer.singleShot(0, self._montar)

    def _excluir(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda) -> None:
        self.editando = None
        if not self.controle.excluir_proposta(venda, proposta):
            self.editando = proposta.id

    def editar_venda(self, venda: vendas_mod.ResumoDaVenda) -> bool:
        if not self.pode_descartar():
            return False
        dialogo = VendaDialog(self, venda=venda)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return False
        self.editando = None
        self.gravou.emit(f"{ControleDasVendas.nome(venda)}: venda alterada.")
        return True

    def nova_venda(self, cpf: str | None = None) -> bool:
        """Cria a venda (so cliente e equipamentos; `cpf` ja escolhe o cliente) e deixa o card dela aberto, pronto
        pro primeiro banco. Quem mostra a lista rele (o card novo so aparece ai)."""
        if not sessao_mod.eh_admin() or not self.pode_descartar():
            return False
        dialogo = VendaDialog(self, cpf=cpf)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return False
        self.aberta, self.editando = dialogo.id_venda, None
        return True
