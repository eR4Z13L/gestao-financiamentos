"""Tela Dashboard de Propostas.

Tudo calculado em tempo real a partir de CLIENTES e PROPOSTAS - nada fica
salvo, so exibido. O botao "Atualizar" rele o .xlsx do zero, pro caso do
arquivo ter sido editado direto no Excel enquanto o app estava aberto.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core import dashboard as dashboard_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core.formatting import formatar_reais
from desktop.table_model import PandasTableModel
from desktop.widgets.metric_card import MetricCard


class DashboardScreen(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        cabecalho = QHBoxLayout()
        titulo = QLabel("📊 Dashboard de Propostas")
        titulo.setProperty("role", "titulo")
        cabecalho.addWidget(titulo)
        cabecalho.addStretch()
        botao_atualizar = QPushButton("Atualizar")
        botao_atualizar.setProperty("role", "botao_primario")
        botao_atualizar.clicked.connect(self._carregar_dados)
        cabecalho.addWidget(botao_atualizar)
        layout.addLayout(cabecalho)

        linha1 = QHBoxLayout()
        self._card_total = MetricCard("Total de propostas")
        self._card_em_analise = MetricCard("Em análise")
        self._card_aprovadas = MetricCard("Aprovadas")
        self._card_negadas = MetricCard("Negadas")
        for card in (self._card_total, self._card_em_analise, self._card_aprovadas, self._card_negadas):
            linha1.addWidget(card, 1)
        layout.addLayout(linha1)

        linha2 = QHBoxLayout()
        self._card_taxa_aprovacao = MetricCard("Taxa de aprovação")
        self._card_taxa_reprovacao = MetricCard("Taxa de reprovação")
        self._card_valor_aprovado = MetricCard("Valor total aprovado")
        for card in (self._card_taxa_aprovacao, self._card_taxa_reprovacao, self._card_valor_aprovado):
            linha2.addWidget(card, 1)
        layout.addLayout(linha2)

        # so aparece quando Aprovadas + Negadas + Em Análise nao soma o Total
        # (proposta com status em branco ou nao reconhecido) - sem isso, o
        # "sumiço" so ficava visivel rolando ate a tabela de detalhamento.
        self._aviso_gap = QLabel("")
        self._aviso_gap.setProperty("role", "secundario")
        self._aviso_gap.setWordWrap(True)
        self._aviso_gap.setVisible(False)
        layout.addWidget(self._aviso_gap)

        subtitulo_status = QLabel("Detalhamento por status")
        subtitulo_status.setProperty("role", "subtitulo")
        layout.addWidget(subtitulo_status)

        legenda_status = QLabel(
            "Qualquer status além de 'Negado' e 'Em Análise' conta como aprovado nas taxas acima. "
            "Use esta tabela para ver onde as propostas aprovadas estão parando "
            "(ex: aprovada mas nunca virou Nota Fiscal Anexada ou Garantia Assinada)."
        )
        legenda_status.setProperty("role", "secundario")
        legenda_status.setWordWrap(True)
        layout.addWidget(legenda_status)

        self._modelo_status = PandasTableModel()
        self._tabela_status = QTableView()
        self._tabela_status.setModel(self._modelo_status)
        self._configurar_tabela(self._tabela_status)
        layout.addWidget(self._tabela_status, stretch=1)

        # "Desempenho por vendedor" nao faz sentido pro proprio vendedor ver
        # (seria uma tabela de 1 linha so, redundante com os cards acima) -
        # so aparece pro ADMIN, que ve a empresa inteira.
        self._secao_vendedor = QWidget()
        layout_secao_vendedor = QVBoxLayout(self._secao_vendedor)
        layout_secao_vendedor.setContentsMargins(0, 0, 0, 0)
        layout_secao_vendedor.setSpacing(16)

        subtitulo_vendedor = QLabel("Desempenho por vendedor")
        subtitulo_vendedor.setProperty("role", "subtitulo")
        layout_secao_vendedor.addWidget(subtitulo_vendedor)

        self._modelo_vendedor = PandasTableModel()
        self._tabela_vendedor = QTableView()
        self._tabela_vendedor.setModel(self._modelo_vendedor)
        self._configurar_tabela(self._tabela_vendedor)
        layout_secao_vendedor.addWidget(self._tabela_vendedor, stretch=1)

        layout.addWidget(self._secao_vendedor, stretch=1)
        self._secao_vendedor.setVisible(not sessao_mod.eh_vendedor())

        self._carregar_dados()

    @staticmethod
    def _configurar_tabela(tabela: QTableView) -> None:
        tabela.setAlternatingRowColors(True)
        tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tabela.horizontalHeader().setStretchLastSection(True)
        tabela.verticalHeader().setVisible(False)

    def _carregar_dados(self) -> None:
        try:
            propostas = propostas_mod.listar_propostas()
        except FileNotFoundError:
            QMessageBox.critical(
                self,
                "Arquivo não encontrado",
                "Não foi possível encontrar o arquivo de dados (.xlsx). Confira o caminho configurado em config.py.",
            )
            return
        except Exception as exc:  # arquivo corrompido, formato inesperado, etc. - nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar dados", str(exc))
            return

        totais = dashboard_mod.totais_gerais(propostas)
        self._card_total.definir_valor(str(totais["total_propostas"]))
        self._card_em_analise.definir_valor(str(totais["em_analise"]))
        self._card_aprovadas.definir_valor(str(totais["aprovadas"]))
        self._card_negadas.definir_valor(str(totais["negadas"]))
        self._card_taxa_aprovacao.definir_valor(f"{totais['taxa_aprovacao']:.1f}%")
        self._card_taxa_reprovacao.definir_valor(f"{totais['taxa_reprovacao']:.1f}%")
        self._card_valor_aprovado.definir_valor(formatar_reais(totais["valor_aprovado"]))

        avisos = []
        gap = totais["sem_status"] + totais["nao_identificado"]
        if gap:
            avisos.append(
                f"⚠️ {gap} proposta(s) não entram nos cards acima (status em branco ou não reconhecido)."
            )
        if totais["aprovadas_sem_valor"]:
            avisos.append(
                f"⚠️ {totais['aprovadas_sem_valor']} proposta(s) aprovada(s) sem valor preenchido - "
                "não entram no 'Valor total aprovado' (não são tratadas como R$ 0)."
            )
        if avisos:
            avisos.append("Veja o detalhamento por status abaixo.")
            self._aviso_gap.setText("\n".join(avisos))
        self._aviso_gap.setVisible(bool(avisos))

        detalhamento = dashboard_mod.detalhamento_por_status(propostas).copy()
        detalhamento["Valor (R$)"] = detalhamento["Valor (R$)"].map(formatar_reais)
        self._modelo_status.definir_dataframe(detalhamento)
        self._tabela_status.resizeColumnsToContents()

        if not sessao_mod.eh_vendedor():
            vendedor = dashboard_mod.por_vendedor(propostas).copy()
            vendedor["Valor Aprovado (R$)"] = vendedor["Valor Aprovado (R$)"].map(formatar_reais)
            self._modelo_vendedor.definir_dataframe(vendedor)
            self._tabela_vendedor.resizeColumnsToContents()
