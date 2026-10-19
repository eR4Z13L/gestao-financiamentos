"""Formulario de lancamento/edicao de proposta: o que aparece dentro do card aberto (o card da venda, o card de
proposta de Todas as Propostas e da Ficha, e o card "Nova proposta").

Mesmo formulario serve pra tres casos:
- cpf fixo + proposta=None -> nova proposta pra um cliente ja conhecido
  (aberta a partir da Ficha de Cliente); com `base`, ja vem preenchida a partir de outra proposta
- cpf fixo + proposta+indice -> abrir uma proposta existente
- cpf=None -> nova proposta "avulsa" (sem um cliente pre-selecionado): mostra um
  campo de cliente pesquisavel na primeira linha.

Os campos ficam numa grade compacta (Data, Meses e Status numa linha; Valor,
Carencia e Parcela na outra; Equipamento e Banco na terceira; so as Observacoes ocupam
a largura toda) - cada um
com a largura que o conteudo pede, pro card expandido ser o menos alto possivel.

Uma proposta existente abre primeiro em MODO LEITURA (campos travados - mesma
caixa da edicao, mas so pra ler/selecionar -, com um botao de copiar ao lado
de cada um, e os botoes Editar e Recolher). So depois de "Editar" o
formulario vira o de edicao, com OK/Cancelar - e Cancelar descarta o que foi digitado e
VOLTA pra leitura (so "Recolher" fecha o card). Proposta nova abre direto em
edicao (nao ha o que "voltar"): Cancelar avisa `cancelada`.

O formulario nao sabe onde esta: quem o hospeda (a lista de vendas ou a de propostas) reage aos
sinais - `gravada` (salvou; `indice_gravado` diz qual proposta), `recolher_pedido`
(Recolher, ou Esc na leitura) e `cancelada` (Cancelar/Esc numa proposta nova).
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QDate, QEvent, QObject, Qt, Signal
from PySide6.QtGui import QIntValidator, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
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

from core import bancos as bancos_mod
from core import clientes as clientes_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendas as vendas_mod
from desktop.widgets.botao_copiar import BotaoCopiar
from desktop.widgets.campo_data import CampoData
from desktop.widgets.campos_da_venda import LinhasDeEquipamento
from desktop.widgets.combo_travavel import ComboTravavel
from desktop.widgets.perguntas_da_venda import perguntar_se_perdida

_CARACTERES_MINIMOS_DO_COMBO = 8  # o combo encolhe ate isso; sem isto o mais largo dos nomes de equipamento decide
_ESPACO_ENTRE_CAMPOS = 12
_ALTURA_OBSERVACOES = 60
VENDA_NOVA_COM_A_PROPOSTA = "+ Venda nova com esta proposta"


def _combo_flexivel(combo: QComboBox) -> None:
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(_CARACTERES_MINIMOS_DO_COMBO)


class _IgnoraRoda(QObject):
    """O formulario mora dentro de uma lista que rola: a roda do mouse sobre um combo ou um campo de numero tem que
    ROLAR a lista, nunca trocar o valor - nem com o campo selecionado (pedido do usuario em 04/10: rolando a pagina com
    o mouse passando por um campo clicado antes, o valor mudava sem ele perceber)."""

    def eventFilter(self, objeto, evento) -> bool:
        if evento.type() == QEvent.Type.Wheel:
            evento.ignore()  # sem aceitar, o evento sobe pro pai e a lista rola
            return True
        return False


class _CaixasDeEquipamento(QWidget):
    """Os equipamentos de uma proposta que esta numa venda: uma caixinha por equipamento da venda (decidido com o
    usuario em 03/10/2026) - desmarca o que este banco nao financia. Responde como o combo (currentText /
    setCurrentText / definir_travado) pra o resto do formulario nao precisar saber qual dos dois e."""

    def __init__(self, equipamentos_da_venda: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "transparente")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self.caixas: list[QCheckBox] = []
        for nome in equipamentos_da_venda:
            self._nova_caixa(nome)

    def _nova_caixa(self, nome: str) -> QCheckBox:
        caixa = QCheckBox(nome, self)
        caixa.setChecked(True)
        self._layout.addWidget(caixa)
        self.caixas.append(caixa)
        return caixa

    def currentText(self) -> str:
        return equipamentos_mod.SEPARADOR.join(c.text() for c in self.caixas if c.isChecked())

    def setCurrentText(self, texto: str) -> None:
        """Marca so os citados em `texto`; vazio (proposta nova) marca todos - por padrao o pedido cobre a venda
        toda. Um nome que nao e da venda (proposta de antes) vira mais uma caixinha, marcada."""
        nomes = equipamentos_mod.nomes_do_texto(texto)
        chaves = {n.upper() for n in nomes}
        for caixa in self.caixas:
            caixa.setChecked(not nomes or caixa.text().upper() in chaves)
        conhecidos = {c.text().upper() for c in self.caixas}
        for nome in nomes:
            if nome.upper() not in conhecidos:
                self._nova_caixa(nome).setChecked(True)

    def definir_travado(self, travar: bool) -> None:
        self._travado = travar
        for caixa in self.caixas:
            caixa.setEnabled(not travar)

    def travado(self) -> bool:
        return getattr(self, "_travado", False)


class _EquipamentoDaEscolha(QWidget):
    """O equipamento da "Nova proposta" que escolhe a venda: as caixinhas da venda escolhida, ou - venda nova - as
    linhas de equipamento (uma por equipamento, como no card "Nova venda"). Responde como os outros dois."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "transparente")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._travado = False
        self.atual: _CaixasDeEquipamento | LinhasDeEquipamento = LinhasDeEquipamento(self)
        self._layout.addWidget(self.atual)

    def trocar(self, equipamentos_da_venda: list[str]) -> None:
        """As caixinhas destes equipamentos (os da venda escolhida); [] = venda nova: as linhas de equipamento."""
        self.atual.hide()
        self.atual.deleteLater()
        self.atual = _CaixasDeEquipamento(equipamentos_da_venda, self) if equipamentos_da_venda else LinhasDeEquipamento(self)
        self.atual.definir_travado(self._travado)
        self._layout.addWidget(self.atual)

    def currentText(self) -> str:
        return self.atual.currentText()

    def setCurrentText(self, texto: str) -> None:
        self.atual.setCurrentText(texto)

    def definir_travado(self, travar: bool) -> None:
        self._travado = travar
        self.atual.definir_travado(travar)

    def travado(self) -> bool:
        return self._travado


class FormularioProposta(QWidget):
    gravada = Signal()
    recolher_pedido = Signal()
    cancelada = Signal()
    # emitido ANTES de `gravada`, so quando o status acabou de virar "Efetivado" (nao
    # quando ja estava): (cpf, equipamento, indice_gravado). Quem escuta (a lista de propostas)
    # oferece encerrar as outras propostas em aberto da mesma venda - ver
    # desktop/widgets/encerrar_propostas_da_venda.py. Emitido ANTES de `gravada` de
    # proposito: depois dela o card e recarregado/recriado, e este `self` pode nao
    # continuar valido.
    efetivada_agora = Signal(str, str, int)

    def __init__(
        self,
        cpf: str | None,
        nome_cliente: str | None = None,
        proposta: dict | None = None,
        indice: int | None = None,
        base: dict | None = None,
        parent: QWidget | None = None,
        *,
        so_edicao: bool = False,
        escolher_venda: bool = False,
    ):
        """`base`: valores iniciais de uma proposta NOVA (ver
        propostas_mod.dados_para_duplicar); ignorado se `proposta` existe. `so_edicao`: dentro do card da venda
        aberto - abre direto editando (a leitura e a propria linha do banco no card) e Cancelar fecha o formulario
        (avisa `cancelada`) em vez de voltar pra leitura. `escolher_venda` (proposta nova, cliente na busca): o
        "+ Nova proposta" de Todas as Propostas - depois do cliente, a venda: uma em aberto dele (a proposta entra
        nela) ou "+ Venda nova com esta proposta" (cria a venda junto)."""
        super().__init__(parent)
        self._so_edicao = so_edicao
        self._cpf = cpf
        self._indice = indice
        self._nome_cliente = nome_cliente
        self._existente = proposta is not None
        self._proposta_original = proposta  # o que "Cancelar" restaura, e o que o arquivo tem que ainda ter ao gravar
        self._foco_inicial_no_banco = proposta is None and base is not None  # vinda de outra proposta: o banco e o que falta escolher
        # proposta nova: grava criando a venda junto, ou - vinda do "+ Adicionar proposta" do card da venda - dentro dela
        self._id_venda = (base or {}).get("ID_VENDA", "") if proposta is None else ""
        self._modo_leitura = False
        self._botoes_copiar: list[BotaoCopiar] = []
        self._clientes_por_rotulo: dict[str, str] = {}
        self._escolher_venda = escolher_venda and proposta is None and cpf is None
        self._venda_combo: ComboTravavel | None = None
        self._vendas_em_aberto: dict[str, vendas_mod.ResumoDaVenda] = {}
        self._cpf_das_vendas: str | None = None  # o cliente cujas vendas o combo da venda mostra
        self.indice_gravado: int | None = None  # a posicao real da proposta gravada (depois de `gravada`)

        origem = proposta if proposta is not None else base
        # uma proposta antiga SEM data pode continuar sem (nao inventamos uma data); as demais exigem
        self._data_em_branco_permitida = self._existente and not self._tem_data(proposta)

        self.setProperty("role", "transparente")  # o card tem o fundo dele; o QSS global pintaria o da janela
        self.setProperty("formulario_proposta", True)  # (ver theme.py: fundo dos campos de numero e das observacoes)
        self._roda = _IgnoraRoda(self)

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
        if self._escolher_venda:
            self._venda_combo = ComboTravavel()
            _combo_flexivel(self._venda_combo)
            self._venda_combo.installEventFilter(self._roda)
            raiz.addWidget(self._celula("Venda *", self._venda_combo, None))

        self._data = CampoData(permitir_futuro=True)  # o mesmo campo do filtro de periodo: da pra apagar/selecionar tudo
        self._valor = QDoubleSpinBox()
        self._valor.setRange(0, 10_000_000)
        self._valor.setDecimals(2)
        self._valor.setPrefix("R$ ")
        self._valor.setGroupSeparatorShown(True)
        self._meses = QSpinBox()
        self._meses.setRange(0, 120)
        # condicoes do banco: em quantos dias vem a 1a parcela (as comuns pra escolher, ou digitar outra) e o valor
        # da parcela que o banco devolve; as duas opcionais (proposta antiga nao tem)
        self._carencia = ComboTravavel()
        self._carencia.setEditable(True)
        self._carencia.addItems([str(dias) for dias in propostas_mod.CARENCIAS_COMUNS])
        self._carencia.lineEdit().setValidator(QIntValidator(0, propostas_mod.CARENCIA_MAXIMA_DIAS, self))
        self._carencia.lineEdit().setPlaceholderText("dias")
        self._carencia.setMinimumContentsLength(4)
        self._parcela = QDoubleSpinBox()
        self._parcela.setRange(0, 10_000_000)
        self._parcela.setDecimals(2)
        self._parcela.setPrefix("R$ ")
        self._parcela.setGroupSeparatorShown(True)

        # o equipamento sempre vem do cadastro (Cadastros > Equipamentos), nunca digitado: numa venda, as caixinhas com
        # os equipamentos dela; fora de uma venda, a lista fechada (como a do banco)
        equipamentos_da_venda = self._equipamentos_da_venda((origem or {}).get("ID_VENDA"))
        if self._escolher_venda:
            self._equipamento = _EquipamentoDaEscolha()
        elif equipamentos_da_venda:
            self._equipamento = _CaixasDeEquipamento(equipamentos_da_venda)
        else:
            self._equipamento = ComboTravavel()
            _combo_flexivel(self._equipamento)
        # a lista de sugestoes so serve pra digitar/escolher (edicao). Vendedor
        # nunca edita e pode estar numa maquina sem o .xlsx local (le do Google
        # Sheets), onde ler as sugestoes falharia - abre a leitura sem elas.
        if not sessao_mod.eh_vendedor() and not equipamentos_da_venda and not self._escolher_venda:
            self._equipamento.addItems(equipamentos_mod.nomes_ativos())

        # lista FECHADA: os bancos ativos do cadastro (Administracao > Cadastros) + "Todos"
        self._banco = ComboTravavel()
        _combo_flexivel(self._banco)
        if not sessao_mod.eh_vendedor():
            self._banco.addItems([*bancos_mod.nomes_ativos(), bancos_mod.BANCO_TODOS])

        self._status = ComboTravavel()
        _combo_flexivel(self._status)
        # proposta nova so nasce com uma resposta de banco; o andamento do negocio fica na venda (core/vendas.py)
        # proposta numa venda: so as 4 respostas do banco (o andamento do negocio fica na venda); as de antes das vendas
        # ainda tem a lista antiga ate a limpeza dos status antigos
        na_venda = bool((proposta or {}).get("ID_PROPOSTA")) or not self._existente
        opcoes_status = list(vendas_mod.STATUS_DA_PROPOSTA if na_venda else propostas_mod.STATUS_OPCOES)
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

        for campo in (self._valor, self._meses, self._carencia, self._parcela, self._equipamento, self._banco, self._status):
            campo.installEventFilter(self._roda)

        # -- a grade: cada campo com a largura que o conteudo pede (o que sobra fica vazio) ----------
        # texto_do_campo recebe o proprio campo e devolve o texto a copiar
        celula_data = self._celula("Data", self._data, lambda c: c.texto(), maximo=190)
        # sem o "R$ " (cleanText) - quem cola isso num sistema de banco quase nunca quer o prefixo;
        # 0 = campo nao preenchido, entao nao ha o que copiar
        celula_valor = self._celula("Valor solicitado *", self._valor, lambda c: c.cleanText() if c.value() else "", maximo=210)
        celula_meses = self._celula("Meses", self._meses, lambda c: str(c.value()) if c.value() else "", maximo=120)
        celula_carencia = self._celula("Carência (dias)", self._carencia, lambda c: c.currentText().strip(), maximo=140)
        celula_parcela = self._celula("Parcela", self._parcela, lambda c: c.cleanText() if c.value() else "", maximo=190)
        if self._escolher_venda:
            rotulo_equipamento = "Equipamento(s) *"
        elif equipamentos_da_venda:
            rotulo_equipamento = "Equipamentos que este pedido cobre *"
        else:
            rotulo_equipamento = "Equipamento *"
        celula_equipamento = self._celula(rotulo_equipamento,
                                          self._equipamento, lambda c: c.currentText().strip(), alinhar_topo=True)
        celula_banco = self._celula("Banco/financeira *", self._banco, lambda c: c.currentText().strip(), maximo=260)
        celula_status = self._celula("Status", self._status, lambda c: c.currentText().strip(), maximo=250)
        celula_obs = self._celula("Observações", self._observacoes, lambda c: c.toPlainText().strip(), alinhar_topo=True)

        for celulas in (
            ((celula_data, 3), (celula_meses, 2), (celula_status, 4)),
            # o valor com as condicoes do banco que mudam a parcela: em quantos dias vem a 1a e quanto ela fica
            ((celula_valor, 3), (celula_carencia, 2), (celula_parcela, 3)),
            ((celula_equipamento, 6), (celula_banco, 4)),
        ):
            linha = QHBoxLayout()
            linha.setSpacing(_ESPACO_ENTRE_CAMPOS)
            for celula, peso in celulas:
                linha.addWidget(celula, peso)
            linha.addStretch(1)
            raiz.addLayout(linha)
        raiz.addWidget(celula_obs)

        if self._escolher_venda:
            self._atualizar_vendas()
            self._cliente_combo.currentTextChanged.connect(lambda _t: self._atualizar_vendas())
            self._venda_combo.currentIndexChanged.connect(lambda _i: self._ao_escolher_venda())
        self._preencher_campos(origem)

        # travados, data/valor/meses ganham a caixa dos combos (mais alta que o
        # visual nativo deles - ver theme.py); a mesma altura minima sempre
        # evita que as linhas "pulem" ao alternar entre leitura e edicao
        self._banco.ensurePolished()
        altura_caixa = self._banco.sizeHint().height()
        for campo in (self._data.campo, self._valor, self._meses, self._parcela):
            campo.setMinimumHeight(altura_caixa)

        # Editar/Recolher so em modo leitura; OK/Cancelar so em modo edicao -
        # _aplicar_modo() alterna a visibilidade
        self._botao_editar = self._botao("Editar", self._habilitar_edicao)
        self._botao_recolher = self._botao("Recolher", self.recolher_pedido.emit)
        self._botao_ok = self._botao("OK", self._salvar)
        self._botao_cancelar = self._botao("Cancelar", self._cancelar_edicao)
        linha_botoes = QHBoxLayout()
        linha_botoes.setSpacing(8)
        linha_botoes.addStretch(1)
        for botao in (self._botao_editar, self._botao_recolher, self._botao_ok, self._botao_cancelar):
            linha_botoes.addWidget(botao)
        raiz.addLayout(linha_botoes)

        self._aplicar_modo(leitura=self._existente and not so_edicao)

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

        carencia = proposta.get("CARÊNCIA (DIAS)") if proposta else None
        self._carencia.setCurrentText(str(int(carencia)) if carencia is not None and not pd.isna(carencia) else "")
        parcela = proposta.get("PARCELA (R$)") if proposta else None
        self._parcela.setValue(float(parcela) if parcela is not None and not pd.isna(parcela) else 0)

        self._definir_equipamento(proposta.get("EQUIPAMENTO", "") if proposta else "")
        self._definir_banco(proposta.get("BANCO", "") if proposta else "")

        status_atual = (proposta.get("STATUS") if proposta else "") or ""
        if status_atual:
            self._status.setCurrentText(status_atual)

        self._observacoes.setPlainText(proposta.get("OBSERVAÇÕES", "") if proposta else "")
        self._estado_inicial = self._estado_atual()

    # -- a escolha da venda ("+ Nova proposta" de Todas as Propostas) ----------------------------------

    def _atualizar_vendas(self) -> None:
        """As vendas em aberto do cliente escolhido, a mais recente marcada; sem nenhuma (ou sem cliente), a venda
        nova. So refaz quando o cliente muda de verdade (digitar o nome nao rele a cada letra)."""
        cpf = self._clientes_por_rotulo.get(self._cliente_combo.currentText().strip())
        if cpf == self._cpf_das_vendas and self._venda_combo.count():
            return
        self._cpf_das_vendas = cpf
        try:
            vendas = vendas_mod.vendas_em_aberto_do_cliente(cpf) if cpf else []
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.warning(self, "Não foi possível ler as vendas do cliente", f"{type(exc).__name__}: {exc}")
            vendas = []
        self._vendas_em_aberto = {v.id: v for v in vendas}
        self._venda_combo.blockSignals(True)
        self._venda_combo.clear()
        for venda in vendas:
            self._venda_combo.addItem(vendas_mod.rotulo_da_venda(venda), venda.id)
        self._venda_combo.addItem(VENDA_NOVA_COM_A_PROPOSTA, "")
        self._venda_combo.setCurrentIndex(0)
        self._venda_combo.blockSignals(False)
        self._ao_escolher_venda()

    def _ao_escolher_venda(self) -> None:
        self._id_venda = self._venda_combo.currentData() or ""
        venda = self._vendas_em_aberto.get(self._id_venda)
        self._equipamento.trocar(equipamentos_mod.nomes_do_texto(venda.equipamentos) if venda is not None else [])

    @staticmethod
    def _equipamentos_da_venda(id_venda) -> list[str]:
        """Os equipamentos da venda da proposta ([] fora de uma venda, ou se a venda nao existe mais)."""
        if not id_venda:
            return []
        vendas = bd.ler_vendas(propostas_mod.CAMINHO_XLSX)
        da_venda = vendas.loc[vendas["ID_VENDA"] == id_venda, "EQUIPAMENTOS"]
        return equipamentos_mod.nomes_do_texto(da_venda.iloc[0]) if len(da_venda) else []

    def _definir_equipamento(self, texto) -> None:
        """Seleciona o que a proposta cita. Na lista fechada, um nome fora do cadastro (desativado, ou de antes dele)
        entra so para esta proposta - editar outra coisa nunca troca o equipamento sem a pessoa escolher."""
        texto = texto.strip() if isinstance(texto, str) else ""
        if not isinstance(self._equipamento, QComboBox):  # as caixinhas da venda, ou a escolha da venda
            self._equipamento.setCurrentText(texto)
            return
        if not texto:
            self._equipamento.setCurrentIndex(-1)
            return
        indice = self._equipamento.findText(texto, Qt.MatchFlag.MatchFixedString | Qt.MatchFlag.MatchCaseSensitive)
        if indice < 0:
            self._equipamento.insertItem(0, texto)
            indice = 0
        self._equipamento.setCurrentIndex(indice)

    def _definir_banco(self, nome) -> None:
        """Seleciona o banco gravado na proposta, EXATAMENTE como esta. Um banco fora da lista (desativado,
        ou numa grafia de antes do cadastro) entra nela so para esta proposta: editar outra coisa nunca troca
        o banco sem a pessoa escolher."""
        nome = nome.strip() if isinstance(nome, str) else ""
        if not nome:
            self._banco.setCurrentIndex(-1)
            return
        indice = self._banco.findText(nome, Qt.MatchFlag.MatchFixedString | Qt.MatchFlag.MatchCaseSensitive)
        if indice < 0:
            self._banco.insertItem(0, nome)
            indice = 0
        self._banco.setCurrentIndex(indice)

    def _estado_atual(self) -> tuple:
        return (
            self._cliente_combo.currentText().strip() if self._cliente_combo is not None else "",
            self._data.texto(),
            self._valor.value(),
            self._meses.value(),
            self._carencia.currentText().strip(),
            self._parcela.value(),
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
        return (self._data, self._valor, self._meses, self._carencia, self._parcela, self._equipamento, self._banco,
                self._status, self._observacoes)

    # -- modo leitura x edicao ------------------------------------------------------

    def _aplicar_modo(self, leitura: bool) -> None:
        self._modo_leitura = leitura
        self._travar_campos(leitura)

        for botao in self._botoes_copiar:
            botao.setVisible(leitura)

        # VENDEDOR nunca escreve nada (core/sessao.py) - nao faz sentido nem
        # oferecer estes botoes; a barreira de verdade continua sendo a do core/
        self._botao_editar.setVisible(leitura and sessao_mod.eh_admin())
        self._botao_recolher.setVisible(leitura)
        self._botao_ok.setVisible(not leitura)
        self._botao_cancelar.setVisible(not leitura)
        # sem isso, Enter em modo leitura poderia cair em "Editar"
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
        for campo in (self._valor, self._meses, self._parcela):
            campo.setReadOnly(travar)
            # setas de "sobe/desce" so fazem sentido editando
            campo.setButtonSymbols(
                QAbstractSpinBox.ButtonSymbols.NoButtons if travar else QAbstractSpinBox.ButtonSymbols.UpDownArrows
            )
        self._observacoes.setReadOnly(travar)
        # o QSS (desktop/theme.py) so da caixa a estes tres quando travados
        for campo in (self._valor, self._meses, self._parcela, self._observacoes):
            campo.setProperty("travado", travar)
            campo.style().unpolish(campo)
            campo.style().polish(campo)
        for combo in (self._equipamento, self._banco, self._status, self._carencia):
            combo.definir_travado(travar)

    def _habilitar_edicao(self) -> None:
        self._aplicar_modo(leitura=False)
        self._data.campo.setFocus()

    def _cancelar_edicao(self) -> None:
        """Cancelar: descarta o que foi digitado e VOLTA pra leitura sem recolher
        o card. Numa proposta nova nao ha leitura pra onde voltar - avisa
        `cancelada` e quem hospeda decide (tirar o card, ou voltar pra proposta de origem)."""
        if not self._existente or self._so_edicao:
            self.cancelada.emit()
            return
        self._preencher_campos(self._proposta_original)
        self._aplicar_modo(leitura=True)
        self._botao_recolher.setFocus()

    # -- teclado e mouse --------------------------------------------------------------

    def keyPressEvent(self, evento: QKeyEvent) -> None:
        # o que o QDialog fazia sozinho: Esc age como o botao Cancelar (edicao) ou Recolher
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

        if isinstance(self._equipamento, _CaixasDeEquipamento) and not self._equipamento.currentText():
            # sem nenhuma marcada, o pedido viraria "a venda toda" (o padrao de um pedido sem equipamento)
            QMessageBox.warning(self, "Nenhum equipamento marcado", "Marque pelo menos um equipamento que este pedido cobre.")
            return
        if isinstance(self._equipamento, _EquipamentoDaEscolha) and not self._equipamento.currentText():
            if self._id_venda:
                QMessageBox.warning(self, "Nenhum equipamento marcado",
                                    "Marque pelo menos um equipamento que este pedido cobre.")
            else:
                QMessageBox.warning(self, "Equipamento em branco", "Informe pelo menos um equipamento da venda nova.")
            return
        banco = self._banco.currentText().strip()
        status = self._status.currentText().strip()
        if not self._existente and not banco:
            QMessageBox.warning(self, "Banco em branco", "Escolha o banco/financeira para onde a proposta vai.")
            return
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
            "CARÊNCIA (DIAS)": self._carencia.currentText().strip(),
            "PARCELA (R$)": self._parcela.value() or "",
            "EQUIPAMENTO": self._equipamento.currentText().strip(),
            "BANCO": banco,
            "STATUS": status,
            "OBSERVAÇÕES": self._observacoes.toPlainText().strip(),
        }
        todas_negadas = False
        try:
            if self._indice is None:
                if self._id_venda:
                    id_proposta = vendas_mod.mandar_a_outro_banco(self._id_venda, campos)
                else:
                    # "Laser X + Cadeira Y" no equipamento: uma venda com os dois, e esta proposta cobrindo ambos
                    _, id_proposta = vendas_mod.criar_venda(cpf, campos["EQUIPAMENTO"].split("+"), campos)
                self.indice_gravado = vendas_mod.indice_da_proposta(id_proposta)
            elif (self._proposta_original or {}).get("ID_PROPOSTA"):
                # numa venda: pelo mesmo caminho da tela Vendas (troca de status com as regras e no historico);
                # pelo ID, entao a posicao que a tela tinha nao importa
                id_proposta = self._proposta_original["ID_PROPOSTA"]
                sem_cpf = {coluna: valor for coluna, valor in campos.items() if coluna != "CPF"}
                todas_negadas = vendas_mod.editar_proposta(id_proposta, sem_cpf, esperado=self._proposta_original)
                self.indice_gravado = vendas_mod.indice_da_proposta(id_proposta)
            else:
                # `esperado`: se a linha desse indice ja nao for a proposta que abrimos (outra tela
                # mexeu no arquivo), recusa em vez de gravar por cima de outra
                propostas_mod.atualizar_proposta(self._indice, campos, esperado=self._proposta_original)
                self.indice_gravado = self._indice
        except (propostas_mod.ErroProposta, vendas_mod.ErroVenda) as exc:
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

        if todas_negadas:  # a ultima resposta negou: a venda esta Perdida? (pergunta; nunca decide sozinho)
            perguntar_se_perdida(self, self._proposta_original["ID_VENDA"], self._nome_cliente or cpf)
        status_anterior = (self._proposta_original or {}).get("STATUS") or ""
        if propostas_mod.eh_efetivado(status) and not propostas_mod.eh_efetivado(status_anterior):
            # o status ACABOU de virar Efetivado (nao ja estava): pode haver outras
            # propostas em aberto da mesma venda (mesmo cliente+equipamento) em outro
            # banco - emite ANTES de `gravada` (ver o comentario do sinal)
            self.efetivada_agora.emit(cpf, campos["EQUIPAMENTO"], self.indice_gravado)
        self.gravada.emit()
