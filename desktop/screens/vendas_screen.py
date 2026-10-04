"""Tela Vendas: um card por venda (cliente + equipamentos), com uma linha por banco para onde ela foi mandada.

Os cards sao a peca de desktop/widgets/card_da_venda.py (a mesma da Ficha de Cliente e da visao por banco): fechados,
servem pra ver e trocar status; um por vez fica ABERTO (dois cliques, ou a setinha do canto), ocupando a linha toda,
pra editar as propostas ali dentro. Esta tela cuida da lista (busca, filtros, "Carregar mais"), de qual card esta
aberto e de nunca descartar algo digitado sem perguntar.

"+ Nova venda" cria so a venda (cliente, equipamentos); os bancos entram depois pelo "+ Adicionar proposta" do card.
Propostas de antes das vendas, ainda nao juntadas, aparecem num aviso com o "Juntar em vendas...".
So o ADMIN ve esta tela (a do VENDEDOR, so leitura, ainda nao existe).
"""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import sessao as sessao_mod
from core import vendas as vendas_mod
from core.validators import apenas_digitos
from desktop.dialogs import organizar_vendas_dialog
from desktop.dialogs.venda_dialog import VendaDialog
from desktop.vigia_do_arquivo import VigiaDoArquivo
from desktop.widgets.botao_recarregar import criar_botao_recarregar
from desktop.widgets.card_da_venda import LARGURA_CARD, NOVA, CardDaVenda, ControleDasVendas, proposta_por_id

_ESPACO = 12
TAMANHO_PAGINA = 30
SEGUNDOS_DO_AVISO = 8

FILTRO_EM_ANDAMENTO = "Em andamento"
FILTRO_PARADAS = f"Paradas há {vendas_mod.DIAS_PARA_ALERTA} dias ou mais"
FILTRO_EFETIVADAS = "Efetivadas"
FILTRO_PERDIDAS = "Perdidas e não efetivadas"
FILTRO_TODAS = "Todas"
FILTROS = [FILTRO_EM_ANDAMENTO, FILTRO_PARADAS, FILTRO_EFETIVADAS, FILTRO_PERDIDAS, FILTRO_TODAS]

_FRASE_STATUS = {  # (singular, plural) na contagem do topo
    vendas_mod.VENDA_AGUARDANDO: ("aguardando bancos", "aguardando bancos"),
    vendas_mod.VENDA_EM_ANDAMENTO: ("em andamento", "em andamento"),
    vendas_mod.VENDA_EFETIVADA: ("efetivada", "efetivadas"),
    vendas_mod.VENDA_NAO_EFETIVADA: ("não efetivada", "não efetivadas"),
    vendas_mod.VENDA_PERDIDA: ("perdida", "perdidas"),
}


def passa_no_filtro(venda: vendas_mod.ResumoDaVenda, filtro: str) -> bool:
    if filtro == FILTRO_EM_ANDAMENTO:
        return not venda.finalizada
    if filtro == FILTRO_PARADAS:
        return venda.parada
    if filtro == FILTRO_EFETIVADAS:
        return venda.status == vendas_mod.VENDA_EFETIVADA
    if filtro == FILTRO_PERDIDAS:
        return venda.status in vendas_mod.DESFECHOS_DA_VENDA
    return True


def passa_na_busca(venda: vendas_mod.ResumoDaVenda, termo: str) -> bool:
    termo = termo.strip().upper()
    if not termo:
        return True
    texto = " ".join([venda.cliente, venda.cpf, venda.equipamentos, venda.vendedor,
                      *(p.banco for p in venda.propostas), *(p.equipamento for p in venda.propostas)]).upper()
    digitos = apenas_digitos(termo)
    return termo in texto or (len(digitos) >= 3 and digitos in apenas_digitos(venda.cpf))


def resumo_por_status(vendas: list[vendas_mod.ResumoDaVenda]) -> str:
    contagem = Counter(v.status for v in vendas)
    partes = []
    for status in vendas_mod.STATUS_DA_VENDA:
        if contagem.get(status):
            singular, plural = _FRASE_STATUS[status]
            partes.append(f"{contagem[status]} {singular if contagem[status] == 1 else plural}")
    return " · ".join(partes)


class VendasScreen(QWidget):
    dados_atualizados = Signal()  # gravou algo: quem mostra dado derivado (Dashboard, selo) rele
    ficha_pedida = Signal(str)  # cpf

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._vigia = VigiaDoArquivo()
        self._vendas: list[vendas_mod.ResumoDaVenda] = []
        self._limite = TAMANHO_PAGINA
        self._colunas = 1
        self.cards: list[CardDaVenda] = []
        self.aberta: str | None = None  # o ID_VENDA do card aberto
        self.editando: str | None = None  # no card aberto: o ID_PROPOSTA no formulario, NOVA, ou None
        self.controle = ControleDasVendas(self, self._depois_de_gravar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        cabecalho = QHBoxLayout()
        layout.addLayout(cabecalho)
        titulo = QLabel("💼 Vendas")
        titulo.setProperty("role", "titulo")
        cabecalho.addWidget(titulo)
        cabecalho.addStretch()
        cabecalho.addWidget(criar_botao_recarregar(lambda *_: self._ao_recarregar()))
        self.botao_nova = QPushButton("+ Nova venda")
        self.botao_nova.setProperty("role", "botao_primario")
        self.botao_nova.clicked.connect(lambda: self.nova_venda())
        cabecalho.addWidget(self.botao_nova)

        self.aviso_sem_venda = QFrame()
        self.aviso_sem_venda.setProperty("role", "chip_filtro")
        linha_aviso = QHBoxLayout(self.aviso_sem_venda)
        linha_aviso.setContentsMargins(12, 6, 8, 6)
        self.texto_sem_venda = QLabel("")
        self.texto_sem_venda.setWordWrap(True)
        linha_aviso.addWidget(self.texto_sem_venda, stretch=1)
        juntar = QPushButton("Juntar em vendas…")
        juntar.clicked.connect(self._juntar_em_vendas)
        linha_aviso.addWidget(juntar)
        self.aviso_sem_venda.setVisible(False)
        layout.addWidget(self.aviso_sem_venda)

        filtros = QHBoxLayout()
        layout.addLayout(filtros)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("🔎 Buscar por cliente, CPF, equipamento ou banco")
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(lambda *_: self._montar(voltar_ao_inicio=True))
        filtros.addWidget(self.busca, stretch=1)
        self.filtro = QComboBox()
        self.filtro.addItems(FILTROS)
        self.filtro.currentIndexChanged.connect(lambda *_: self._montar(voltar_ao_inicio=True))
        filtros.addWidget(self.filtro)

        self.contador = QLabel("")
        self.contador.setProperty("role", "secundario")
        layout.addWidget(self.contador)

        self._conteudo = QWidget()
        self._conteudo.setProperty("role", "transparente")
        coluna = QVBoxLayout(self._conteudo)
        coluna.setContentsMargins(0, 0, 4, 0)
        self._grade = QGridLayout()
        self._grade.setSpacing(_ESPACO)
        self._grade.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        coluna.addLayout(self._grade)
        self.vazio = QLabel("", self._conteudo)
        self.vazio.setProperty("role", "secundario")
        coluna.addWidget(self.vazio)
        self.botao_mais = QPushButton("Carregar mais", self._conteudo)
        self.botao_mais.clicked.connect(self._carregar_mais)
        coluna.addWidget(self.botao_mais, alignment=Qt.AlignmentFlag.AlignLeft)
        coluna.addStretch()
        self.rolagem = QScrollArea()
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setFrameShape(QFrame.Shape.NoFrame)
        self.rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rolagem.setWidget(self._conteudo)
        layout.addWidget(self.rolagem, stretch=1)

        # "Santander: "Em Análise" → "Aprovado"." - o que acabou de mudar; some sozinha (desfazer = a setinha ↩)
        self.faixa_aviso = QFrame()
        self.faixa_aviso.setProperty("role", "chip_filtro")
        linha_faixa = QHBoxLayout(self.faixa_aviso)
        linha_faixa.setContentsMargins(12, 6, 8, 6)
        self.texto_aviso = QLabel("")
        linha_faixa.addWidget(self.texto_aviso, stretch=1)
        self.faixa_aviso.setVisible(False)
        layout.addWidget(self.faixa_aviso)
        self._relogio_aviso = QTimer(self)
        self._relogio_aviso.setSingleShot(True)
        self._relogio_aviso.timeout.connect(lambda: self.faixa_aviso.setVisible(False))

        self.carregar()

    # -- dados --------------------------------------------------------------------------------------

    def carregar(self) -> bool:
        self._vigia.registrar_leitura()
        try:
            self._vendas = vendas_mod.listar_vendas()
            sem_venda = vendas_mod.contar_propostas_sem_venda()
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar as vendas", f"{type(exc).__name__}: {exc}")
            return False
        if self.aberta not in {v.id for v in self._vendas}:
            self.aberta, self.editando = None, None
        self.texto_sem_venda.setText(
            f"{sem_venda} proposta(s) de antes das vendas ainda não estão em nenhuma venda e não aparecem aqui."
        )
        self.aviso_sem_venda.setVisible(sem_venda > 0)
        self._montar()
        return True

    def tem_edicao_pendente(self) -> bool:
        card = self.card_aberto()
        return card is not None and card.tem_alteracoes()

    def recarregar_se_mudou(self) -> bool:
        """A cada tique da janela com esta tela aberta: rele se o arquivo mudou por fora (outra tela gravou,
        baixou da nuvem, restaurou backup) - menos com algo digitado no formulario aberto. True se releu."""
        if self._vigia.mudou_desde_a_leitura() and not self.tem_edicao_pendente():
            return self.carregar()
        return False

    def _ao_recarregar(self) -> None:
        if self._pode_descartar():
            self.carregar()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self.recarregar_se_mudou()

    def vendas_visiveis(self) -> list[vendas_mod.ResumoDaVenda]:
        filtro = self.filtro.currentText()
        return [v for v in self._vendas
                if v.id == self.aberta or (passa_no_filtro(v, filtro) and passa_na_busca(v, self.busca.text()))]

    # -- montagem -----------------------------------------------------------------------------------

    def _montar(self, voltar_ao_inicio: bool = False) -> None:
        if voltar_ao_inicio:
            self._limite = TAMANHO_PAGINA
        rolagem = self.rolagem.verticalScrollBar().value()
        # a lista nao "encolhe" enquanto os cards sao trocados: sem isso a rolagem caia pro topo a cada gravacao (o
        # card que a pessoa estava usando sumia de vista) - a altura so e solta depois de devolver a posicao
        self._conteudo.setMinimumHeight(0 if voltar_ao_inicio else self._conteudo.height())
        for card in self.cards:
            card.hide()  # some ja: o deleteLater so apaga no proximo ciclo
            card.deleteLater()
        self.cards = []
        visiveis = self.vendas_visiveis()
        for venda in visiveis[: self._limite]:
            card = CardDaVenda(venda, self._conteudo, aberto=venda.id == self.aberta)
            self.controle.conectar(card)
            card.abrir_pedido.connect(self.abrir_venda)
            card.fechar_pedido.connect(lambda _v: self.fechar_venda())
            card.proposta_pedida.connect(self.editar_proposta)
            card.edicao_da_venda_pedida.connect(self.editar_venda)
            card.ficha_pedida.connect(self.ficha_pedida)
            if card.aberto and self.editando is not None:
                self._por_formulario(card)
            self.cards.append(card)
        resumo = resumo_por_status(visiveis)
        self.contador.setText(f"{len(visiveis)} venda(s)" + (f" · {resumo}" if resumo else ""))
        if self._vendas:
            self.vazio.setText("Nenhuma venda encontrada com esses filtros.")
        else:
            self.vazio.setText("Nenhuma venda ainda. Clique em \"+ Nova venda\".")
        self.vazio.setVisible(not visiveis)
        self.botao_mais.setVisible(len(visiveis) > self._limite)
        self._posicionar()
        if not voltar_ao_inicio:
            QTimer.singleShot(0, lambda: self._devolver_rolagem(rolagem))

    def _devolver_rolagem(self, valor: int) -> None:
        self.rolagem.verticalScrollBar().setValue(valor)
        self._conteudo.setMinimumHeight(0)

    def _posicionar(self) -> None:
        """Cards fechados lado a lado; o aberto numa linha so dele, na largura toda."""
        while self._grade.count():
            self._grade.takeAt(0)
        linha = coluna = 0
        for card in self.cards:
            if card.aberto:
                if coluna:
                    linha, coluna = linha + 1, 0
                # a largura de todas as colunas mesmo sozinho na lista (sem outro card, as colunas nao tem largura)
                card.setMinimumWidth(self._colunas * LARGURA_CARD + (self._colunas - 1) * _ESPACO)
                self._grade.addWidget(card, linha, 0, 1, self._colunas)
                linha += 1
                continue
            self._grade.addWidget(card, linha, coluna, Qt.AlignmentFlag.AlignTop)
            coluna += 1
            if coluna == self._colunas:
                linha, coluna = linha + 1, 0

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        largura = self.width() - 48 - 4 - self.rolagem.verticalScrollBar().sizeHint().width()
        colunas = max(1, (largura + _ESPACO) // (LARGURA_CARD + _ESPACO))
        if colunas != self._colunas:
            self._colunas = colunas
            self._posicionar()

    def _carregar_mais(self) -> None:
        self._limite += TAMANHO_PAGINA
        self._montar()

    # -- card aberto e formulario -------------------------------------------------------------------

    def card_aberto(self) -> CardDaVenda | None:
        return next((c for c in self.cards if c.aberto), None)

    def _pode_descartar(self) -> bool:
        """Ha algo digitado no formulario aberto? Pergunta antes de descartar."""
        if not self.tem_edicao_pendente():
            return True
        resposta = QMessageBox.question(
            self, "Alterações não salvas", "Há uma proposta com alterações que ainda não foram salvas. Descartar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        return resposta == QMessageBox.StandardButton.Yes

    def abrir_venda(self, venda: vendas_mod.ResumoDaVenda, editando: str | None = None) -> bool:
        if venda.id == self.aberta and editando == self.editando:
            return True
        if not self._pode_descartar():
            return False
        self.aberta, self.editando = venda.id, editando
        self._montar()
        card = self.card_aberto()
        if card is not None:
            QTimer.singleShot(0, lambda: self.rolagem.ensureWidgetVisible(card, 0, 40))
        return True

    def fechar_venda(self) -> bool:
        if not self._pode_descartar():
            return False
        self.aberta, self.editando = None, None
        self._montar()
        return True

    def editar_proposta(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda | None) -> bool:
        """O ✎ (ou dois cliques num banco, ou "+ Adicionar proposta"): abre o card, se preciso, com o formulario."""
        return self.abrir_venda(venda, NOVA if proposta is None else proposta.id)

    def _por_formulario(self, card: CardDaVenda) -> None:
        try:
            formulario = self.controle.criar_formulario(card.venda, self.editando)
        except Exception as exc:  # nunca falhar em silencio (ex.: a proposta sumiu entre a leitura e o clique)
            QMessageBox.warning(self, "Não foi possível abrir a proposta", f"{type(exc).__name__}: {exc}")
            self.editando = None
            return
        formulario.gravada.connect(self._ao_gravar_formulario)
        formulario.cancelada.connect(self._ao_cancelar_formulario)
        ao_excluir = None
        proposta = proposta_por_id(card.venda, self.editando)
        if proposta is not None:
            ao_excluir = lambda: self._excluir(card.venda, proposta)  # noqa: E731
        card.mostrar_formulario(self.editando, formulario, ao_excluir)
        QTimer.singleShot(0, formulario.dar_foco_inicial)

    def _ao_gravar_formulario(self) -> None:
        self.editando = None
        QTimer.singleShot(0, lambda: self._depois_de_gravar("Proposta gravada."))  # fora do sinal do formulario

    def _ao_cancelar_formulario(self) -> None:
        self.editando = None
        QTimer.singleShot(0, self._montar)

    def _excluir(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda) -> None:
        self.editando = None
        if not self.controle.excluir_proposta(venda, proposta):
            self.editando = proposta.id

    def editar_venda(self, venda: vendas_mod.ResumoDaVenda) -> bool:
        if not self._pode_descartar():
            return False
        dialogo = VendaDialog(self, venda=venda)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return False
        self.editando = None
        self._depois_de_gravar(f"{ControleDasVendas.nome(venda)}: venda alterada.")
        return True

    # -- gravar -------------------------------------------------------------------------------------

    def _depois_de_gravar(self, aviso: str = "") -> None:
        self.carregar()
        self.dados_atualizados.emit()
        if aviso:
            self.avisar(aviso)

    def avisar(self, texto: str) -> None:
        self.texto_aviso.setText(texto)
        self.faixa_aviso.setVisible(True)
        self._relogio_aviso.start(SEGUNDOS_DO_AVISO * 1000)

    def nova_venda(self, cpf: str | None = None) -> bool:
        """Cria a venda (so cliente e equipamentos) e ja deixa o card dela aberto, pronto pro primeiro banco."""
        if not sessao_mod.eh_admin() or not self._pode_descartar():
            return False
        dialogo = VendaDialog(self, cpf=cpf)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return False
        self.busca.clear()
        self.filtro.setCurrentText(FILTRO_EM_ANDAMENTO)
        self.aberta, self.editando = dialogo.id_venda, None
        self._depois_de_gravar("Venda criada: agora é só adicionar as propostas dos bancos.")
        return True

    def _juntar_em_vendas(self) -> None:
        if organizar_vendas_dialog.organizar(self):
            self._depois_de_gravar()
