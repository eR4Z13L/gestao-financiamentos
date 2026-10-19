"""Tela Vendas: um card por venda (cliente + equipamentos), com uma linha por banco para onde ela foi mandada.

Os cards sao a peca de desktop/widgets/lista_de_vendas.py (a mesma da Ficha de Cliente e da visao por banco), em
colunas que encaixam: fechados, servem pra ver e trocar status; um por vez fica ABERTO (dois cliques, ou a setinha do
canto), crescendo para baixo na propria coluna, pra editar as propostas ali dentro. Esta tela cuida de QUAIS vendas
aparecem (busca e filtros).

"+ Nova venda" abre o card "Nova venda" no topo da lista (cliente, equipamentos, observacoes - sem janela); criada, o
card dela fica aberto com o formulario do primeiro banco.
Propostas de antes das vendas, ainda nao juntadas, aparecem num aviso com o "Juntar em vendas...".
So o ADMIN ve esta tela (a do VENDEDOR, so leitura, ainda nao existe).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import propostas as propostas_mod
from core import vendas as vendas_mod
from core.validators import apenas_digitos
from desktop.dialogs import organizar_vendas_dialog
from desktop.vigia_do_arquivo import VigiaDoArquivo
from desktop.widgets.botao_recarregar import criar_botao_recarregar
from desktop.widgets.lista_de_vendas import FaixaDeAviso, ListaDeVendas, resumo_por_status

FILTRO_EM_ANDAMENTO = "Em andamento"
FILTRO_PARADAS = f"Paradas há {propostas_mod.DIAS_PROPOSTA_PARADA} dias ou mais"
FILTRO_EFETIVADAS = "Efetivadas"
FILTRO_PERDIDAS = "Perdidas e não efetivadas"
FILTRO_TODAS = "Todas"
FILTROS = [FILTRO_EM_ANDAMENTO, FILTRO_PARADAS, FILTRO_EFETIVADAS, FILTRO_PERDIDAS, FILTRO_TODAS]


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


class VendasScreen(QWidget):
    dados_atualizados = Signal()  # gravou algo: quem mostra dado derivado (Dashboard, selo) rele
    ficha_pedida = Signal(str)  # cpf

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._vigia = VigiaDoArquivo()
        self._vendas: list[vendas_mod.ResumoDaVenda] = []

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
        self.busca.textChanged.connect(lambda *_: self._mostrar(voltar_ao_inicio=True))
        filtros.addWidget(self.busca, stretch=1)
        self.filtro = QComboBox()
        self.filtro.addItems(FILTROS)
        self.filtro.currentIndexChanged.connect(lambda *_: self._mostrar(voltar_ao_inicio=True))
        filtros.addWidget(self.filtro)

        self.contador = QLabel("")
        self.contador.setProperty("role", "secundario")
        layout.addWidget(self.contador)

        conteudo = QWidget()
        conteudo.setProperty("role", "transparente")
        coluna = QVBoxLayout(conteudo)
        coluna.setContentsMargins(0, 0, 4, 0)
        self.rolagem = QScrollArea()
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setFrameShape(QFrame.Shape.NoFrame)
        self.rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rolagem.setWidget(conteudo)
        self.lista = ListaDeVendas(self.rolagem, conteudo)
        self.lista.gravou.connect(self._depois_de_gravar)
        self.lista.ficha_pedida.connect(self.ficha_pedida)
        coluna.addWidget(self.lista)
        coluna.addStretch()
        layout.addWidget(self.rolagem, stretch=1)

        self.faixa_aviso = FaixaDeAviso()
        self.texto_aviso = self.faixa_aviso.texto
        layout.addWidget(self.faixa_aviso)

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
        self.texto_sem_venda.setText(
            f"{sem_venda} proposta(s) de antes das vendas ainda não estão em nenhuma venda e não aparecem aqui."
        )
        self.aviso_sem_venda.setVisible(sem_venda > 0)
        self._mostrar()
        return True

    def tem_edicao_pendente(self) -> bool:
        return self.lista.tem_edicao_pendente()

    def recarregar_se_mudou(self) -> bool:
        """A cada tique da janela com esta tela aberta: rele se o arquivo mudou por fora (outra tela gravou,
        baixou da nuvem, restaurou backup) - menos com algo digitado no formulario aberto. True se releu."""
        if self._vigia.mudou_desde_a_leitura() and not self.tem_edicao_pendente():
            return self.carregar()
        return False

    def _ao_recarregar(self) -> None:
        if self.lista.pode_descartar():
            self.lista.descartar()
            self.carregar()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self.recarregar_se_mudou()

    def vendas_visiveis(self) -> list[vendas_mod.ResumoDaVenda]:
        filtro = self.filtro.currentText()
        return [v for v in self._vendas
                if v.id == self.lista.aberta or (passa_no_filtro(v, filtro) and passa_na_busca(v, self.busca.text()))]

    def _mostrar(self, voltar_ao_inicio: bool = False) -> None:
        visiveis = self.vendas_visiveis()
        if self._vendas:
            vazio = "Nenhuma venda encontrada com esses filtros."
        else:
            vazio = "Nenhuma venda ainda. Clique em \"+ Nova venda\"."
        self.lista.definir_vendas(visiveis, texto_vazio=vazio, voltar_ao_inicio=voltar_ao_inicio)
        resumo = resumo_por_status(visiveis)
        self.contador.setText(f"{len(visiveis)} venda(s)" + (f" · {resumo}" if resumo else ""))

    # -- gravar -------------------------------------------------------------------------------------

    def _depois_de_gravar(self, aviso: str = "") -> None:
        self.carregar()
        self.dados_atualizados.emit()
        self.faixa_aviso.avisar(aviso)

    def avisar(self, texto: str) -> None:
        self.faixa_aviso.avisar(texto)

    def nova_venda(self, cpf: str | None = None) -> bool:
        """O card "Nova venda" no topo da lista (fica mesmo com a busca e o filtro: o digitado nao some). Criada, a
        venda aparece aberta mesmo fora deles (ver vendas_visiveis)."""
        return self.lista.nova_venda(cpf)

    def mostrar_venda(self, id_venda: str, id_proposta: str | None = None) -> bool:
        """Rele e deixa o card da venda `id_venda` aberto e a vista (o "Ver na venda →" de Todas as Propostas), com
        `id_proposta` ja com o formulario dela aberto embaixo da linha do banco. A venda
        aberta aparece mesmo fora da busca e do filtro. False (depois de avisar) se ela nao existe mais, ou se a pessoa
        preferiu continuar editando outra."""
        if not self.carregar():
            return False
        venda = self.lista.venda_por_id(id_venda) or next((v for v in self._vendas if v.id == id_venda), None)
        if venda is None:
            QMessageBox.warning(self, "Venda não encontrada", "Esta venda pode ter sido removida. Recarregue a lista.")
            return False
        # com `id_proposta`, ja com o formulario dela aberto, logo embaixo da linha do banco: da pra ver de qual veio
        if id_proposta and not any(p.id == id_proposta for p in venda.propostas):
            id_proposta = None  # (a proposta saiu da venda nesse meio-tempo: abre so a venda)
        if not self.lista.abrir_venda(venda, id_proposta or None):
            return False
        self._mostrar()  # a aberta entra na lista mesmo que a busca ou o filtro a escondessem
        self.lista.rolar_ate_o_aberto()
        return True

    def _juntar_em_vendas(self) -> None:
        if organizar_vendas_dialog.organizar(self):
            self._depois_de_gravar()
