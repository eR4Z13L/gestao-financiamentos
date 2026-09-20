"""Formulario de lancamento/edicao de proposta: o conteudo do CARD EXPANDIDO (ver
ListaCartoes.expandir e ExpansorDeProposta).

Mesmo formulario serve pra tres casos:
- cpf fixo + proposta=None -> nova proposta pra um cliente ja conhecido
  (aberta a partir da Ficha de Cliente); com `base`, ja vem preenchida (duplicar)
- cpf fixo + proposta+indice -> abrir uma proposta existente
- cpf=None -> nova proposta "avulsa" (aberta a partir da tela Todas as
  Propostas, que nao tem um cliente pre-selecionado): mostra um campo de
  cliente pesquisavel na primeira linha.

Os campos ficam numa grade compacta (Data, Meses e Status numa linha; Valor,
Equipamento e Banco na outra; so as Observacoes ocupam a largura toda) - cada um
com a largura que o conteudo pede, pro card expandido ser o menos alto possivel.

Uma proposta existente abre primeiro em MODO LEITURA (campos travados - mesma
caixa da edicao, mas so pra ler/selecionar -, com um botao de copiar ao lado
de cada um, e os botoes Editar, Duplicar e Recolher). So depois de "Editar" o
formulario vira o de edicao, com OK/Cancel - e Cancel descarta o que foi digitado e
VOLTA pra leitura (so "Recolher" fecha o card). Proposta nova abre direto em
edicao (nao ha o que "voltar"): Cancel avisa `cancelada`.

O formulario nao sabe onde esta: quem o hospeda (ExpansorDeProposta) reage aos
sinais - `gravada` (salvou; `indice_gravado` diz qual proposta), `recolher_pedido`
(Recolher, ou Esc na leitura), `cancelada` (Cancel/Esc numa proposta nova) e
`duplicacao_pedida`.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QDate, QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config import BANCOS_CONHECIDOS
from core import clientes as clientes_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from desktop.widgets.botao_copiar import BotaoCopiar
from desktop.widgets.campo_data import CampoData
from desktop.widgets.combo_travavel import ComboTravavel

_CARACTERES_MINIMOS_DO_COMBO = 8  # o combo encolhe ate isso; sem isto o mais largo dos nomes de equipamento decide
_ESPACO_ENTRE_CAMPOS = 12
_ALTURA_OBSERVACOES = 60


def _combo_flexivel(combo: QComboBox) -> None:
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(_CARACTERES_MINIMOS_DO_COMBO)


class _IgnoraRodaSemFoco(QObject):
    """O formulario mora dentro de uma lista que rola: a roda do mouse sobre um combo ou um campo
    de numero (sem foco nele) tem que ROLAR a lista, nao trocar o valor sem ninguem perceber."""

    def eventFilter(self, objeto, evento) -> bool:
        if evento.type() == QEvent.Type.Wheel and not objeto.hasFocus():
            evento.ignore()  # sem aceitar, o evento sobe pro pai e a lista rola
            return True
        return False


class FormularioProposta(QWidget):
    gravada = Signal()
    recolher_pedido = Signal()
    cancelada = Signal()
    duplicacao_pedida = Signal()

    def __init__(
        self,
        cpf: str | None,
        nome_cliente: str | None = None,
        proposta: dict | None = None,
        indice: int | None = None,
        base: dict | None = None,
        parent: QWidget | None = None,
    ):
        """`base`: valores iniciais de uma proposta NOVA (ver
        propostas_mod.dados_para_duplicar); ignorado se `proposta` existe."""
        super().__init__(parent)
        self._cpf = cpf
        self._indice = indice
        self._nome_cliente = nome_cliente
        self._existente = proposta is not None
        self._proposta_original = proposta  # o que "Cancel" restaura, e o que o arquivo tem que ainda ter ao gravar
        self._foco_inicial_no_banco = proposta is None and base is not None  # duplicata: o banco e o que falta escolher
        self._modo_leitura = False
        self._botoes_copiar: list[BotaoCopiar] = []
        self._clientes_por_rotulo: dict[str, str] = {}
        self.indice_gravado: int | None = None  # a posicao real da proposta gravada (depois de `gravada`)

        origem = proposta if proposta is not None else base
        # uma proposta antiga SEM data pode continuar sem (nao inventamos uma data); as demais exigem
        self._data_em_branco_permitida = self._existente and not self._tem_data(proposta)

        self.setProperty("role", "transparente")  # o card tem o fundo dele; o QSS global pintaria o da janela
        self.setProperty("formulario_proposta", True)  # (ver theme.py: fundo dos campos de numero e das observacoes)
        self._roda = _IgnoraRodaSemFoco(self)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(10)

        if cpf is None:
            self._cliente_combo = QComboBox()
            self._cliente_combo.setEditable(True)
            _combo_flexivel(self._cliente_combo)
            for _, c in clientes_mod.listar_clientes().iterrows():
                rotulo = f"{c['CLIENTE']} — {c['CPF/CNPJ']}"
                self._clientes_por_rotulo[rotulo] = c["CPF/CNPJ"]
            self._cliente_combo.addItems(sorted(self._clientes_por_rotulo.keys()))
            self._cliente_combo.setCurrentText("")
            completador = QCompleter(list(self._clientes_por_rotulo.keys()), self)
            completador.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completador.setFilterMode(Qt.MatchFlag.MatchContains)
            self._cliente_combo.setCompleter(completador)
            self._cliente_combo.installEventFilter(self._roda)
            raiz.addWidget(self._celula("Cliente *", self._cliente_combo, None))
        else:
            self._cliente_combo = None

        self._data = CampoData(permitir_futuro=True)  # o mesmo campo do filtro de periodo: da pra apagar/selecionar tudo
        self._valor = QDoubleSpinBox()
        self._valor.setRange(0, 10_000_000)
        self._valor.setDecimals(2)
        self._valor.setPrefix("R$ ")
        self._valor.setGroupSeparatorShown(True)
        self._meses = QSpinBox()
        self._meses.setRange(0, 120)

        self._equipamento = ComboTravavel()
        self._equipamento.setEditable(True)
        _combo_flexivel(self._equipamento)
        # a lista de sugestoes so serve pra digitar/escolher (edicao). Vendedor
        # nunca edita e pode estar numa maquina sem o .xlsx local (le do Google
        # Sheets), onde ler as sugestoes falharia - abre a leitura sem elas.
        if not sessao_mod.eh_vendedor():
            self._equipamento.addItems(equipamentos_mod.listar_nomes_equipamento())

        self._banco = ComboTravavel()
        self._banco.setEditable(True)
        _combo_flexivel(self._banco)
        self._banco.addItems(BANCOS_CONHECIDOS)

        self._status = ComboTravavel()
        _combo_flexivel(self._status)
        opcoes_status = list(propostas_mod.STATUS_OPCOES)
        status_atual = (origem.get("STATUS") if origem else "") or ""
        if status_atual and status_atual not in opcoes_status:
            # dados antigos tem status em CAIXA ALTA ("APROVADO", "NEGADO")
            # que nao batem com a lista oficial ("Aprovado", "Negado") - sem
            # isso, editar uma proposta assim mudaria o status dela pra "Em
            # Análise" (o primeiro item) sem o usuario perceber.
            opcoes_status.insert(0, status_atual)
        self._status.addItems(opcoes_status)

        self._observacoes = QPlainTextEdit()
        self._observacoes.setFixedHeight(_ALTURA_OBSERVACOES)

        for campo in (self._valor, self._meses, self._equipamento, self._banco, self._status):
            campo.installEventFilter(self._roda)

        # -- a grade: cada campo com a largura que o conteudo pede (o que sobra fica vazio) ----------
        # texto_do_campo recebe o proprio campo e devolve o texto a copiar
        celula_data = self._celula("Data", self._data, lambda c: c.texto(), maximo=190)
        # sem o "R$ " (cleanText) - quem cola isso num sistema de banco quase nunca quer o prefixo;
        # 0 = campo nao preenchido, entao nao ha o que copiar
        celula_valor = self._celula("Valor solicitado *", self._valor, lambda c: c.cleanText() if c.value() else "", maximo=210)
        celula_meses = self._celula("Meses", self._meses, lambda c: str(c.value()) if c.value() else "", maximo=120)
        celula_equipamento = self._celula("Equipamento *", self._equipamento, lambda c: c.currentText().strip())
        celula_banco = self._celula("Banco/financeira *", self._banco, lambda c: c.currentText().strip(), maximo=260)
        celula_status = self._celula("Status", self._status, lambda c: c.currentText().strip(), maximo=250)
        celula_obs = self._celula("Observações", self._observacoes, lambda c: c.toPlainText().strip(), alinhar_topo=True)

        for celulas in (
            ((celula_data, 3), (celula_meses, 2), (celula_status, 4)),
            ((celula_valor, 3), (celula_equipamento, 6), (celula_banco, 4)),
        ):
            linha = QHBoxLayout()
            linha.setSpacing(_ESPACO_ENTRE_CAMPOS)
            for celula, peso in celulas:
                linha.addWidget(celula, peso)
            linha.addStretch(1)
            raiz.addLayout(linha)
        raiz.addWidget(celula_obs)

        self._preencher_campos(origem)

        # travados, data/valor/meses ganham a caixa dos combos (mais alta que o
        # visual nativo deles - ver theme.py); a mesma altura minima sempre
        # evita que as linhas "pulem" ao alternar entre leitura e edicao
        self._banco.ensurePolished()
        altura_caixa = self._banco.sizeHint().height()
        for campo in (self._data.campo, self._valor, self._meses):
            campo.setMinimumHeight(altura_caixa)

        # Editar/Duplicar/Recolher so em modo leitura; OK/Cancel so em modo edicao -
        # _aplicar_modo() alterna a visibilidade
        self._botao_editar = self._botao("Editar", self._habilitar_edicao)
        self._botao_duplicar = self._botao("Duplicar", self.duplicacao_pedida.emit)
        self._botao_recolher = self._botao("Recolher", self.recolher_pedido.emit)
        self._botao_ok = self._botao("OK", self._salvar)
        self._botao_cancelar = self._botao("Cancel", self._cancelar_edicao)
        linha_botoes = QHBoxLayout()
        linha_botoes.setSpacing(8)
        linha_botoes.addStretch(1)
        for botao in (self._botao_editar, self._botao_duplicar, self._botao_recolher, self._botao_ok, self._botao_cancelar):
            linha_botoes.addWidget(botao)
        raiz.addLayout(linha_botoes)

        self._aplicar_modo(leitura=self._existente)

    # -- construcao ---------------------------------------------------------------

    @staticmethod
    def _tem_data(proposta: dict | None) -> bool:
        data = proposta.get("DATA") if proposta else None
        return isinstance(data, pd.Timestamp) and not pd.isna(data)

    @staticmethod
    def _botao(texto: str, ao_clicar) -> QPushButton:
        botao = QPushButton(texto)
        botao.setAutoDefault(False)  # o Enter e tratado em keyPressEvent (o formulario nao esta num QDialog)
        botao.clicked.connect(ao_clicar)
        return botao

    def _celula(self, rotulo: str, campo: QWidget, texto_do_campo, alinhar_topo: bool = False, maximo: int | None = None) -> QWidget:
        """Legenda pequena em cima e o campo embaixo, com um botao Copiar ao lado - o botao so
        aparece em modo leitura (ver _aplicar_modo). `texto_do_campo` recebe o proprio campo e
        devolve o texto a copiar (None: campo sem botao); nao pode capturar `self` (o formulario):
        formulario -> botao -> funcao -> formulario seria um ciclo de referencias, e um widget sem
        pai so seria destruido pelo coletor de lixo, em momento arbitrario (ja causou crash "Aborted"
        nos testes)."""
        celula = QWidget()
        celula.setProperty("role", "transparente")
        if maximo is not None:
            celula.setMaximumWidth(maximo)
        caixa = QVBoxLayout(celula)
        caixa.setContentsMargins(0, 0, 0, 0)
        caixa.setSpacing(3)
        legenda = QLabel(rotulo)
        legenda.setProperty("role", "rotulo_do_cartao")
        caixa.addWidget(legenda)
        linha = QHBoxLayout()
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(4)
        linha.addWidget(campo, stretch=1)
        if texto_do_campo is not None:
            botao = BotaoCopiar(lambda: texto_do_campo(campo))
            self._botoes_copiar.append(botao)
            alinhamento = Qt.AlignmentFlag.AlignTop if alinhar_topo else Qt.AlignmentFlag.AlignVCenter
            linha.addWidget(botao, alignment=alinhamento)
        caixa.addLayout(linha)
        return celula

    def _preencher_campos(self, proposta: dict | None) -> None:
        """Poe em cada campo o valor da proposta (ou o padrao de uma proposta
        nova, se `proposta` for None) - usado ao abrir e tambem ao cancelar a
        edicao, pra descartar o que foi digitado."""
        data_atual = proposta.get("DATA") if proposta else None
        if isinstance(data_atual, pd.Timestamp) and not pd.isna(data_atual):
            self._data.definir_data(QDate(data_atual.year, data_atual.month, data_atual.day))
        elif self._existente:
            self._data.definir_data(None)  # proposta antiga sem data: fica sem (nao inventa uma)
        else:
            self._data.definir_data(QDate.currentDate())

        valor = proposta.get("VALOR (R$)") if proposta else None
        self._valor.setValue(float(valor) if valor is not None and not pd.isna(valor) else 0)

        meses = proposta.get("MESES") if proposta else None
        self._meses.setValue(int(meses) if meses is not None and not pd.isna(meses) else 0)

        self._equipamento.setCurrentText(proposta.get("EQUIPAMENTO", "") if proposta else "")
        self._banco.setCurrentText(proposta.get("BANCO", "") if proposta else "")
        # o cursor fica no FIM do texto depois de preencher e um nome comprido mostraria so o final dele
        for combo in (self._equipamento, self._banco):
            combo.lineEdit().setCursorPosition(0)

        status_atual = (proposta.get("STATUS") if proposta else "") or ""
        if status_atual:
            self._status.setCurrentText(status_atual)

        self._observacoes.setPlainText(proposta.get("OBSERVAÇÕES", "") if proposta else "")
        self._estado_inicial = self._estado_atual()

    def _estado_atual(self) -> tuple:
        return (
            self._cliente_combo.currentText().strip() if self._cliente_combo is not None else "",
            self._data.texto(),
            self._valor.value(),
            self._meses.value(),
            self._equipamento.currentText().strip(),
            self._banco.currentText().strip(),
            self._status.currentText().strip(),
            self._observacoes.toPlainText().strip(),
        )

    def tem_alteracoes(self) -> bool:
        """Ha algo digitado que ainda nao foi gravado? (So faz sentido em edicao: a leitura nao muda.)"""
        return not self._modo_leitura and self._estado_atual() != self._estado_inicial

    def _campos_editaveis(self) -> tuple[QWidget, ...]:
        # o campo de cliente (so existe em proposta nova, que nunca abre em
        # modo leitura) fica de fora de proposito
        return (self._data, self._valor, self._meses, self._equipamento, self._banco, self._status, self._observacoes)

    # -- modo leitura x edicao ------------------------------------------------------

    def _aplicar_modo(self, leitura: bool) -> None:
        self._modo_leitura = leitura
        self._travar_campos(leitura)

        for botao in self._botoes_copiar:
            botao.setVisible(leitura)

        # VENDEDOR nunca escreve nada (core/sessao.py) - nao faz sentido nem
        # oferecer estes botoes; a barreira de verdade continua sendo a do core/
        self._botao_editar.setVisible(leitura and sessao_mod.eh_admin())
        self._botao_duplicar.setVisible(leitura and sessao_mod.eh_admin())
        self._botao_recolher.setVisible(leitura)
        self._botao_ok.setVisible(not leitura)
        self._botao_cancelar.setVisible(not leitura)
        # sem isso, Enter em modo leitura poderia cair em "Editar" ou "Duplicar"
        (self._botao_recolher if leitura else self._botao_ok).setDefault(True)
        (self._botao_ok if leitura else self._botao_recolher).setDefault(False)

    def dar_foco_inicial(self) -> None:
        """Chamado quando o card expande (com o formulario ja visivel)."""
        if self._modo_leitura:
            self._botao_recolher.setFocus()  # o primeiro campo abriria com um pedaco do texto destacado
        elif self._foco_inicial_no_banco:
            self._banco.setFocus()
        elif self._cliente_combo is not None:
            self._cliente_combo.setFocus()
        else:
            self._data.campo.setFocus()

    def _travar_campos(self, travar: bool) -> None:
        """Somente leitura (nao "desabilitado"): o campo mantem a mesma caixa da
        edicao e o texto continua selecionavel/copiavel, mas nada muda."""
        self._data.definir_somente_leitura(travar)
        for campo in (self._valor, self._meses):
            campo.setReadOnly(travar)
            # setas de "sobe/desce" so fazem sentido editando
            campo.setButtonSymbols(
                QAbstractSpinBox.ButtonSymbols.NoButtons if travar else QAbstractSpinBox.ButtonSymbols.UpDownArrows
            )
        self._observacoes.setReadOnly(travar)
        # o QSS (desktop/theme.py) so da caixa a estes tres quando travados
        for campo in (self._valor, self._meses, self._observacoes):
            campo.setProperty("travado", travar)
            campo.style().unpolish(campo)
            campo.style().polish(campo)
        for combo in (self._equipamento, self._banco, self._status):
            combo.definir_travado(travar)

    def _habilitar_edicao(self) -> None:
        self._aplicar_modo(leitura=False)
        self._data.campo.setFocus()

    def _cancelar_edicao(self) -> None:
        """Cancel: descarta o que foi digitado e VOLTA pra leitura sem recolher
        o card. Numa proposta nova nao ha leitura pra onde voltar - avisa
        `cancelada` e quem hospeda decide (tirar o card, ou voltar pra proposta de origem)."""
        if not self._existente:
            self.cancelada.emit()
            return
        self._preencher_campos(self._proposta_original)
        self._aplicar_modo(leitura=True)
        self._botao_recolher.setFocus()

    # -- teclado e mouse --------------------------------------------------------------

    def keyPressEvent(self, evento: QKeyEvent) -> None:
        # o que o QDialog fazia sozinho: Esc age como o botao Cancel (edicao) ou Recolher
        # (leitura); Enter aperta o botao padrao. So chega aqui o que o campo com foco
        # nao usou (um QPlainTextEdit fica com o Enter dele, pra quebrar linha). O formulario
        # ACEITA tudo: senao a tecla subiria pra lista de cards (o Enter dela expande/recolhe).
        tecla = evento.key()
        if tecla == Qt.Key.Key_Escape:
            if self._modo_leitura:
                self.recolher_pedido.emit()
            else:
                self._cancelar_edicao()
        elif tecla in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            for botao in (self._botao_recolher, self._botao_ok):
                if botao.isDefault() and not botao.isHidden() and botao.isEnabled():
                    botao.click()
                    break
        evento.accept()

    def mousePressEvent(self, evento) -> None:
        evento.accept()  # um clique (ou duplo clique) num espaco vazio do formulario nao e um clique no card

    def mouseDoubleClickEvent(self, evento) -> None:
        evento.accept()

    # -- gravar ---------------------------------------------------------------------

    def _resolver_cpf(self) -> str | None:
        if self._cpf is not None:
            return self._cpf
        rotulo = self._cliente_combo.currentText().strip()
        cpf = self._clientes_por_rotulo.get(rotulo)
        if cpf is None:
            QMessageBox.warning(
                self, "Cliente não encontrado", "Selecione um cliente da lista (comece a digitar o nome ou CPF)."
            )
        return cpf

    def _confirmar(self, titulo: str, mensagem: str) -> bool:
        resposta = QMessageBox.question(
            self,
            titulo,
            mensagem,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return resposta == QMessageBox.StandardButton.Yes

    def _duplicata_provavel(self, cpf: str, data: pd.Timestamp, valor) -> bool:
        """Mesmo cliente + mesma data + mesmo valor de outra proposta ja
        lancada (ignorando a que esta sendo editada agora) - um sinal comum
        de duplicidade por engano (ex: clique duplo em "Salvar")."""
        try:
            historico = propostas_mod.historico_por_cpf(cpf)
        except Exception:
            return False  # checagem extra nao pode impedir o salvamento normal
        if self._indice is not None:
            historico = historico[historico.index != self._indice]
        if historico.empty or valor in (None, ""):
            return False
        mesma_data = historico["DATA"] == data
        mesmo_valor = (historico["VALOR (R$)"] - float(valor)).abs() < 0.01
        return bool((mesma_data & mesmo_valor).any())

    def _salvar(self) -> None:
        if self._modo_leitura:
            return  # nao ha botao OK em modo leitura; garante que nenhum outro caminho grave nesse modo
        cpf = self._resolver_cpf()
        if cpf is None:
            return

        data, erro_data = self._data.avaliar()
        if erro_data:
            QMessageBox.warning(self, "Data inválida", erro_data)
            return
        if data is None and not self._data_em_branco_permitida:
            QMessageBox.warning(self, "Data em branco", "Informe a data da proposta (dd/mm/aaaa).")
            return

        banco = self._banco.currentText().strip()
        status = self._status.currentText().strip()
        faltando = [rotulo for rotulo, valor in (("Banco/financeira", banco), ("Status", status)) if not valor]
        if faltando:
            plural = len(faltando) > 1
            if not self._confirmar(
                "Campo recomendado em branco",
                f"{' e '.join(faltando)} não {'foram preenchidos' if plural else 'foi preenchido'}. "
                "Deseja salvar assim mesmo?",
            ):
                return

        data_proposta = pd.Timestamp(data.year(), data.month(), data.day()) if data is not None else ""
        valor_informado = self._valor.value() or ""  # 0 = campo nao preenchido (mesma convencao de MESES)

        if data is not None and self._duplicata_provavel(cpf, data_proposta, valor_informado):
            if not self._confirmar(
                "Possível duplicata",
                "Já existe uma proposta deste cliente com a mesma data e o mesmo valor. "
                "Deseja salvar mesmo assim?",
            ):
                return

        campos = {
            "DATA": data_proposta,
            "CPF": cpf,
            "VALOR (R$)": valor_informado,
            "MESES": self._meses.value() or "",
            "EQUIPAMENTO": self._equipamento.currentText().strip(),
            "BANCO": banco,
            "STATUS": status,
            "OBSERVAÇÕES": self._observacoes.toPlainText().strip(),
        }
        try:
            if self._indice is None:
                self.indice_gravado = propostas_mod.adicionar_proposta(campos)
            else:
                # `esperado`: se a linha desse indice ja nao for a proposta que abrimos (outra tela
                # mexeu no arquivo), recusa em vez de gravar por cima de outra
                propostas_mod.atualizar_proposta(self._indice, campos, esperado=self._proposta_original)
                self.indice_gravado = self._indice
        except propostas_mod.ErroProposta as exc:
            QMessageBox.warning(self, "Não foi possível salvar", str(exc))
            return
        except sessao_mod.PermissaoNegada as exc:
            QMessageBox.warning(self, "Ação não permitida", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao salvar", str(exc))
            return

        self.gravada.emit()
