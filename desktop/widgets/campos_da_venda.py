"""Os campos da venda - cliente, equipamentos e observacoes -, os mesmos onde quer que a venda seja escrita: o card
"Nova venda" no topo da lista de vendas, o "Editar a venda" dentro do card aberto e a proposta que cria a venda junto
("+ Venda nova com esta proposta", em Todas as Propostas). Decidido com o usuario em 05/10/2026: tudo nos cards, sem
janela.

Os equipamentos sao escolhidos da lista do cadastro (Cadastros > Equipamentos), um por linha - nunca digitados -, com
"+ Outro equipamento" e o ✕ para tirar (o primeiro nunca sai: a venda tem pelo menos um). Quem grava e o core
(core/vendas.py); estes campos so juntam o que foi escolhido e dizem o que falta.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QCompleter,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import clientes as clientes_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendas as vendas_mod
from desktop.widgets.combo_travavel import ComboTravavel

SEPARADOR_DE_EQUIPAMENTOS = equipamentos_mod.SEPARADOR


def _botao_link(texto: str, parent: QWidget, ao_clicar) -> QPushButton:
    botao = QPushButton(texto, parent)
    botao.setProperty("role", "botao_link")
    botao.setCursor(Qt.CursorShape.PointingHandCursor)
    botao.clicked.connect(ao_clicar)
    return botao


class LinhasDeEquipamento(QWidget):
    """Um equipamento por linha, da lista fechada do cadastro. Responde como os outros campos de equipamento do
    formulario da proposta (currentText / setCurrentText / definir_travado), para servir tambem a ele."""

    alterado = Signal()

    def __init__(self, parent: QWidget | None = None, nomes: list[str] | None = None):
        super().__init__(parent)
        self.setProperty("role", "transparente")
        self._nomes = list(equipamentos_mod.nomes_ativos() if nomes is None else nomes)
        self._travado = False
        self.linhas: list[ComboTravavel] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self.mais = _botao_link("+ Outro equipamento", self, lambda: self.adicionar(""))
        self._layout.addWidget(self.mais, alignment=Qt.AlignmentFlag.AlignLeft)
        self.vazio: QLabel | None = None
        if not self._nomes:
            self.vazio = QLabel("Nenhum equipamento cadastrado: cadastre em Cadastros > Equipamentos.", self)
            self.vazio.setProperty("role", "aviso")
            self.vazio.setWordWrap(True)
            self._layout.addWidget(self.vazio)
        self.adicionar("")

    def adicionar(self, nome: str) -> ComboTravavel:
        linha = QWidget(self)
        linha.setProperty("role", "transparente")
        caixa = QHBoxLayout(linha)
        caixa.setContentsMargins(0, 0, 0, 0)
        combo = ComboTravavel(linha)  # a roda do mouse nunca troca o equipamento (pedido do usuario em 04/10)
        combo.addItems(self._nomes)
        combo.setPlaceholderText("Escolha o equipamento")
        self._escolher(combo, nome)
        combo.currentIndexChanged.connect(self.alterado)
        caixa.addWidget(combo, stretch=1)
        if self.linhas:  # o primeiro nunca sai: a venda tem pelo menos um equipamento
            tirar = QPushButton("✕", linha)
            tirar.setProperty("role", "botao_icone")
            tirar.setToolTip("Tirar este equipamento")
            tirar.setFixedSize(28, 28)
            tirar.clicked.connect(lambda: self.tirar(combo))
            caixa.addWidget(tirar)
        self._layout.insertWidget(len(self.linhas), linha)  # antes do "+ Outro equipamento", sempre por ultimo
        self.linhas.append(combo)
        combo.definir_travado(self._travado)
        if len(self.linhas) > 1 and not nome:
            combo.setFocus()
        self.alterado.emit()
        return combo

    @staticmethod
    def _escolher(combo: ComboTravavel, nome: str) -> None:
        if not nome:
            combo.setCurrentIndex(-1)
            return
        indice = combo.findText(nome, Qt.MatchFlag.MatchFixedString | Qt.MatchFlag.MatchCaseSensitive)
        if indice < 0:  # um nome de antes do cadastro (ou desativado) fica, so nesta venda
            combo.insertItem(0, nome)
            indice = 0
        combo.setCurrentIndex(indice)

    def tirar(self, combo: ComboTravavel) -> None:
        if combo not in self.linhas or len(self.linhas) == 1:
            return
        self.linhas.remove(combo)
        linha = combo.parentWidget()
        linha.hide()
        linha.deleteLater()
        self.alterado.emit()

    def equipamentos(self) -> list[str]:
        return [c.currentText().strip() for c in self.linhas if c.currentText().strip()]

    # -- o mesmo jeito dos outros campos de equipamento do formulario da proposta --------------------------------

    def currentText(self) -> str:
        return SEPARADOR_DE_EQUIPAMENTOS.join(self.equipamentos())

    def setCurrentText(self, texto: str) -> None:
        nomes = equipamentos_mod.nomes_do_texto(texto)
        while len(self.linhas) > 1:
            self.tirar(self.linhas[-1])
        self._escolher(self.linhas[0], nomes[0] if nomes else "")
        for nome in nomes[1:]:
            self.adicionar(nome)

    def definir_travado(self, travar: bool) -> None:
        self._travado = travar
        for combo in self.linhas:
            combo.definir_travado(travar)
        self.mais.setVisible(not travar)

    def travado(self) -> bool:
        return self._travado


class CamposDaVenda(QWidget):
    """Cliente, equipamentos e observacoes. `venda`: editar esta (o cliente nao muda); `cpf`: venda nova ja com o
    cliente (a Ficha); sem os dois, o cliente e escolhido na busca (nome ou CPF)."""

    cliente_mudou = Signal(object)  # o CPF escolhido (None: nenhum)

    def __init__(self, parent: QWidget | None = None, *, venda: vendas_mod.ResumoDaVenda | None = None,
                 cpf: str | None = None, com_observacoes: bool = True):
        super().__init__(parent)
        self.setProperty("role", "transparente")
        self._venda = venda
        self._cpf_fixo = venda.cpf if venda is not None else cpf
        self._clientes_por_rotulo: dict[str, str] = {}
        formulario = QFormLayout(self)
        formulario.setContentsMargins(0, 0, 0, 0)
        formulario.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.cliente: ComboTravavel | None = None
        self.rotulo_cliente: QLabel | None = None
        if self._cpf_fixo is not None:
            nome = venda.cliente if venda is not None else self._nome_do_cliente(cpf)
            self.rotulo_cliente = QLabel(f"<b>{nome or self._cpf_fixo}</b>", self)
            formulario.addRow("Cliente", self.rotulo_cliente)
        else:
            self.cliente = ComboTravavel(self)
            self.cliente.setEditable(True)
            for _, c in clientes_mod.listar_clientes().iterrows():
                self._clientes_por_rotulo[f"{c['CLIENTE']} — {c['CPF/CNPJ']}"] = c["CPF/CNPJ"]
            self.cliente.addItems(sorted(self._clientes_por_rotulo))
            self.cliente.setCurrentText("")
            completador = QCompleter(list(self._clientes_por_rotulo), self)
            completador.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completador.setFilterMode(Qt.MatchFlag.MatchContains)
            self.cliente.setCompleter(completador)
            self.cliente.lineEdit().setPlaceholderText("Digite o nome ou o CPF")
            self.cliente.currentTextChanged.connect(lambda _t: self.cliente_mudou.emit(self.cpf()))
            formulario.addRow("Cliente *", self.cliente)

        self.equipamentos = LinhasDeEquipamento(self)
        atuais = equipamentos_mod.nomes_do_texto(venda.equipamentos) if venda is not None else []
        if atuais:
            self.equipamentos.setCurrentText(SEPARADOR_DE_EQUIPAMENTOS.join(atuais))
        formulario.addRow("Equipamento(s) *", self.equipamentos)

        self.observacoes: QPlainTextEdit | None = None
        if com_observacoes:
            self.observacoes = QPlainTextEdit(self)
            self.observacoes.setFixedHeight(60)
            self.observacoes.setPlainText(venda.observacoes if venda is not None else "")
            formulario.addRow("Observações", self.observacoes)
        self._inicial = self._estado()

    @staticmethod
    def _nome_do_cliente(cpf: str | None) -> str:
        cliente = clientes_mod.buscar_por_cpf(cpf) if cpf else None
        return (cliente or {}).get("CLIENTE", "") or ""

    def cpf(self) -> str | None:
        if self._cpf_fixo is not None:
            return self._cpf_fixo
        return self._clientes_por_rotulo.get(self.cliente.currentText().strip())

    def nome_do_cliente(self) -> str:
        if self._venda is not None:
            return self._venda.cliente or self._venda.cpf
        rotulo = self.cliente.currentText().strip() if self.cliente is not None else ""
        return rotulo.split(" — ")[0] if rotulo in self._clientes_por_rotulo else self._nome_do_cliente(self.cpf())

    def texto_das_observacoes(self) -> str:
        return self.observacoes.toPlainText().strip() if self.observacoes is not None else ""

    def o_que_falta(self) -> tuple[str, str] | None:
        """(titulo, mensagem) do que falta para gravar; None: pode gravar."""
        if self.cpf() is None:
            return "Cliente não encontrado", "Escolha um cliente da lista (comece a digitar o nome ou o CPF)."
        if not self.equipamentos.equipamentos():
            return "Equipamento em branco", "Informe pelo menos um equipamento da venda."
        return None

    def _estado(self) -> tuple:
        return (self.cliente.currentText().strip() if self.cliente is not None else "",
                tuple(self.equipamentos.equipamentos()), self.texto_das_observacoes())

    def tem_alteracoes(self) -> bool:
        return self._estado() != self._inicial

    def dar_foco_inicial(self) -> None:
        (self.cliente or self.equipamentos.linhas[0]).setFocus()


class FormularioDaVenda(QWidget):
    """Os campos da venda com os botoes: "Criar venda" (o card "Nova venda") ou "Gravar" (o "Editar a venda" do card
    aberto), e "Cancelar". Grava pelo core e avisa `gravada` com o ID_VENDA; quem hospeda decide o resto."""

    gravada = Signal(str)  # ID_VENDA
    cancelada = Signal()

    def __init__(self, parent: QWidget | None = None, *, venda: vendas_mod.ResumoDaVenda | None = None,
                 cpf: str | None = None):
        super().__init__(parent)
        self.setProperty("role", "transparente")
        self._venda = venda
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(10)
        self.campos = CamposDaVenda(self, venda=venda, cpf=cpf)
        raiz.addWidget(self.campos)
        botoes = QHBoxLayout()
        botoes.setSpacing(8)
        botoes.addStretch(1)
        self.botao_gravar = QPushButton("Criar venda" if venda is None else "Gravar", self)
        self.botao_gravar.setProperty("role", "botao_primario")
        self.botao_gravar.setDefault(True)
        self.botao_gravar.clicked.connect(self.gravar)
        self.botao_cancelar = QPushButton("Cancelar", self)
        self.botao_cancelar.clicked.connect(self.cancelada)
        botoes.addWidget(self.botao_gravar)
        botoes.addWidget(self.botao_cancelar)
        raiz.addLayout(botoes)

    def tem_alteracoes(self) -> bool:
        return self.campos.tem_alteracoes()

    def dar_foco_inicial(self) -> None:
        self.campos.dar_foco_inicial()

    def gravar(self) -> bool:
        falta = self.campos.o_que_falta()
        if falta is not None:
            QMessageBox.warning(self, *falta)
            return False
        equipamentos = self.campos.equipamentos.equipamentos()
        observacoes = self.campos.texto_das_observacoes()
        try:
            if self._venda is None:
                id_venda, _ = vendas_mod.criar_venda(self.campos.cpf(), equipamentos, observacoes=observacoes)
            else:
                vendas_mod.editar_venda(self._venda.id, equipamentos, observacoes)
                id_venda = self._venda.id
        except (vendas_mod.ErroVenda, propostas_mod.ErroProposta) as exc:
            QMessageBox.warning(self, "Não foi possível gravar", str(exc))
            return False
        except sessao_mod.PermissaoNegada as exc:
            QMessageBox.warning(self, "Ação não permitida", str(exc))
            return False
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return False
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao gravar", f"{type(exc).__name__}: {exc}")
            return False
        self.gravada.emit(id_venda)
        return True

    # -- teclado e mouse (como o formulario da proposta) ------------------------------------------------------

    def keyPressEvent(self, evento: QKeyEvent) -> None:
        # Esc cancela; Enter cria/grava (as observacoes ficam com o Enter delas). Aceita tudo: senao a tecla subiria
        # para a lista de cards
        if evento.key() == Qt.Key.Key_Escape:
            self.cancelada.emit()
        elif evento.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.botao_gravar.click()
        evento.accept()

    def mousePressEvent(self, evento) -> None:
        evento.accept()  # um clique (ou dois) num espaco vazio do formulario nao e um clique no card

    def mouseDoubleClickEvent(self, evento) -> None:
        evento.accept()
