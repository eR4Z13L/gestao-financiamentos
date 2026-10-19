"""A lista de cards de venda, a mesma na tela Vendas e na Ficha de Cliente.

Os cards ficam em colunas que encaixam (desktop/widgets/colunas_que_encaixam.py, a mesma peca da lista de propostas);
esta lista cuida de qual esta ABERTO (um por vez: ele so cresce para baixo, na propria coluna), do formulario dentro
dele (o de uma proposta, ou o "Editar a venda"), do card "Nova venda" no topo e de nunca descartar algo digitado sem
perguntar. Quem mostra a lista decide QUAIS vendas
aparecem (busca, filtros, o cliente da ficha) e rele depois de gravar: a lista avisa pelo sinal `gravou`.
"""

from __future__ import annotations

from collections import Counter
from typing import Callable

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QScrollArea, QWidget

from core import sessao as sessao_mod
from core import vendas as vendas_mod
from desktop.widgets.campos_da_venda import FormularioDaVenda
from desktop.widgets.card_da_venda import (
    EDITAR_VENDA,
    LARGURA_CARD,
    NOVA,
    CardDaVenda,
    CardNovaVenda,
    ControleDasVendas,
    proposta_por_id,
)
from desktop.widgets.colunas_que_encaixam import ListaEmColunas

SEGUNDOS_DO_AVISO = 8
NOVA_VENDA = "nova_venda"  # o item (e a chave) do card "Nova venda" no topo
AVISO_VENDA_CRIADA = "Venda criada: agora é só adicionar as propostas dos bancos."

_FRASE_STATUS = {  # (singular, plural) nas contagens
    vendas_mod.VENDA_AGUARDANDO: ("aguardando bancos", "aguardando bancos"),
    vendas_mod.VENDA_EM_ANDAMENTO: ("em andamento", "em andamento"),
    vendas_mod.VENDA_EFETIVADA: ("efetivada", "efetivadas"),
    vendas_mod.VENDA_PENDENTE_ENTREGA: ("pendente de entrega", "pendentes de entrega"),
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
        self.editando: str | None = None  # no card aberto: o ID_PROPOSTA no formulario, NOVA, EDITAR_VENDA ou None
        self.rascunho: dict | None = None  # o card "Nova venda" no topo: {"cpf"} (None: o cliente se escolhe nele)
        self._vendas: list[vendas_mod.ResumoDaVenda] = []
        self.antes_de_editar: Callable[[], bool] | None = None  # False: nao abre o formulario (ver abrir_venda)
        self.controle = ControleDasVendas(self, self.gravou.emit)

    # -- vendas -------------------------------------------------------------------------------------

    def definir_vendas(self, vendas: list[vendas_mod.ResumoDaVenda], *, texto_vazio: str = "",
                       voltar_ao_inicio: bool = False) -> None:
        """As vendas a mostrar, na ordem. `voltar_ao_inicio`: outra lista (busca, filtro, outro cliente) - volta
        a primeira pagina e nao devolve a rolagem; senao (releu depois de gravar) tudo fica onde estava."""
        if self.aberta not in {v.id for v in vendas}:
            self.aberta, self.editando = None, None
        self._vendas = list(vendas)
        self._remontar(texto_vazio, voltar_ao_inicio)

    def _remontar(self, texto_vazio: str | None = None, voltar_ao_inicio: bool = False) -> None:
        itens = ([NOVA_VENDA] if self.rascunho is not None else []) + self._vendas
        self._definir_itens(itens, self.vazio.text() if texto_vazio is None else texto_vazio, voltar_ao_inicio)

    def total(self) -> int:
        return len(self._vendas)

    def _chave(self, item) -> str:
        return NOVA_VENDA if item == NOVA_VENDA else item.id

    def _posicao_que_precisa_aparecer(self) -> int | None:
        """O card aberto nunca fica alem da pagina carregada (o "Ver na venda →" de Todas as Propostas): ele aparece."""
        if self.aberta is None:
            return None
        return next((i for i, v in enumerate(self._itens) if v != NOVA_VENDA and v.id == self.aberta), None)

    def _criar_card(self, venda) -> CardDaVenda | CardNovaVenda:
        if venda == NOVA_VENDA:
            return self._card_do_rascunho()
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
        if self.rascunho is not None:
            novo = self.card_da_nova_venda()
            if novo is not None:
                return NOVA_VENDA, novo.formulario
        card = self.card_aberto()
        if card is None or card.formulario is None or self.editando is None:
            return None
        return f"{card.venda.id}|{self.editando}", card.formulario

    def venda_por_id(self, id_venda: str) -> vendas_mod.ResumoDaVenda | None:
        return next((v for v in self._vendas if v.id == id_venda), None)

    # -- card aberto e formulario -------------------------------------------------------------------

    def card_aberto(self) -> CardDaVenda | None:
        return next((c for c in self.cards if c.aberto), None)

    def card_da_nova_venda(self) -> CardNovaVenda | None:
        return next((c for c in self.cards if isinstance(c, CardNovaVenda)), None)

    def tem_edicao_pendente(self) -> bool:
        return any(c is not None and c.tem_alteracoes() for c in (self.card_aberto(), self.card_da_nova_venda()))

    def pode_descartar(self) -> bool:
        """Ha algo digitado no formulario aberto? Pergunta antes de descartar."""
        if not self.tem_edicao_pendente():
            return True
        resposta = QMessageBox.question(
            self, "Alterações não salvas", "Há alterações que ainda não foram salvas. Descartar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        return resposta == QMessageBox.StandardButton.Yes

    def descartar(self) -> None:
        """Fecha o formulario sem perguntar (quem chama ja perguntou ou avisou)."""
        if self.editando is not None or self.rascunho is not None or self.tem_edicao_pendente():
            self.editando, self.rascunho = None, None
            self._remontar()

    def liberar(self) -> bool:
        """Fecha o formulario (o card continua aberto), perguntando antes de descartar o digitado. False = a pessoa
        preferiu continuar editando (quem chamou nao segue)."""
        if self.editando is None and self.rascunho is None:
            return True
        if not self.pode_descartar():
            return False
        self.editando, self.rascunho = None, None
        self._remontar()
        return True

    def abrir_venda(self, venda: vendas_mod.ResumoDaVenda, editando: str | None = None) -> bool:
        if venda.id == self.aberta and editando == self.editando and self.rascunho is None:
            return True
        if not self.pode_descartar():
            return False
        # na Ficha ha outro formulario (o do historico do VENDEDOR): um por vez na tela
        if editando is not None and self.antes_de_editar is not None and not self.antes_de_editar():
            return False
        self.aberta, self.editando, self.rascunho = venda.id, editando, None
        self._remontar()
        self.rolar_ate_o_aberto()
        return True

    def rolar_ate_o_aberto(self) -> None:
        self.rolar_ate(self.card_aberto())

    def fechar_venda(self) -> bool:
        if not self.pode_descartar():
            return False
        self.aberta, self.editando, self.rascunho = None, None, None
        self._remontar()
        return True

    def editar_proposta(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda | None) -> bool:
        """O ✎ (ou dois cliques num banco, ou "+ Adicionar proposta"): abre o card, se preciso, com o formulario."""
        return self.abrir_venda(venda, NOVA if proposta is None else proposta.id)

    def _por_formulario(self, card: CardDaVenda) -> None:
        if self.editando == EDITAR_VENDA:
            self._por_edicao_da_venda(card)
            return
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
        QTimer.singleShot(0, self._remontar)

    def _excluir(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda) -> None:
        self.editando = None
        if not self.controle.excluir_proposta(venda, proposta):
            self.editando = proposta.id

    # -- a venda: editar no card aberto, e o card "Nova venda" ---------------------------------------

    def editar_venda(self, venda: vendas_mod.ResumoDaVenda) -> bool:
        """O "Editar a venda": no proprio card aberto, os equipamentos e as observacoes viram campos (sem janela)."""
        if not sessao_mod.eh_admin():
            return False
        return self.abrir_venda(venda, EDITAR_VENDA)

    def _por_edicao_da_venda(self, card: CardDaVenda) -> None:
        formulario = self._formulario_guardado(f"{card.venda.id}|{EDITAR_VENDA}")
        if formulario is None:
            formulario = FormularioDaVenda(venda=card.venda)
            nome = ControleDasVendas.nome(card.venda)
            formulario.gravada.connect(lambda _id: self._ao_gravar_venda(f"{nome}: venda alterada."))
            formulario.cancelada.connect(self._ao_cancelar_formulario)
            QTimer.singleShot(0, formulario.dar_foco_inicial)
        card.mostrar_formulario(EDITAR_VENDA, formulario)

    def _ao_gravar_venda(self, aviso: str) -> None:
        self.editando = None
        QTimer.singleShot(0, lambda: self.gravou.emit(aviso))  # fora do sinal do formulario

    def nova_venda(self, cpf: str | None = None) -> bool:
        """O card "Nova venda" no topo (`cpf`: ja com o cliente, a Ficha). Um por vez: se ja ha um, ele fica (com o que
        foi digitado). Criada a venda, o card dela fica aberto com o formulario do primeiro banco."""
        if not sessao_mod.eh_admin():
            return False
        if self.rascunho is not None and self.rascunho["cpf"] == cpf:
            self.rolar_ate(self.card_da_nova_venda())
            return True
        if not self.pode_descartar():
            return False
        if self.antes_de_editar is not None and not self.antes_de_editar():  # na Ficha: o outro formulario
            return False
        self.aberta, self.editando, self.rascunho = None, None, {"cpf": cpf}
        self._remontar()
        self.rolar_ate(self.card_da_nova_venda())
        return True

    def _card_do_rascunho(self) -> CardNovaVenda:
        formulario = self._formulario_guardado(NOVA_VENDA)
        if formulario is None:
            formulario = FormularioDaVenda(cpf=self.rascunho["cpf"])
            formulario.gravada.connect(self._ao_criar_venda)
            formulario.cancelada.connect(self._ao_cancelar_nova_venda)
            QTimer.singleShot(0, formulario.dar_foco_inicial)
        return CardNovaVenda(formulario, self)

    def _ao_criar_venda(self, id_venda: str) -> None:
        # o card da venda nova, aberto, ja com o formulario do primeiro banco (da pra cancelar e deixar sem proposta)
        self.aberta, self.editando, self.rascunho = id_venda, NOVA, None
        QTimer.singleShot(0, lambda: self._avisar_criada(id_venda))  # fora do sinal do formulario

    def _avisar_criada(self, id_venda: str) -> None:
        self.gravou.emit(AVISO_VENDA_CRIADA)
        self.rolar_ate_o_aberto()

    def _ao_cancelar_nova_venda(self) -> None:
        self.rascunho = None
        QTimer.singleShot(0, self._remontar)
