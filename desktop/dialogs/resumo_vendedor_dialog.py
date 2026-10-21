"""O diálogo "Resumo por vendedor" da tela Vendas (plano 1.5-B): escolhe o vendedor, o período (sugestões Semana,
Quinzena e Mês, atual ou anterior, que PREENCHEM as datas "de" e "até"; as datas também se editam à mão), quais blocos
entram, mostra a prévia do texto e copia para o WhatsApp. Só mostra e copia: quem monta o texto é
core/resumo_vendas.py (nada é gravado).
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import resumo_vendas as resumo_mod
from core import vendedores as vendedores_mod

TODOS = "Todos"
PERSONALIZADO = "Personalizado"
# (rotulo, tipo, qual): as sugestoes de periodo
SUGESTOES = [
    ("Esta semana", resumo_mod.SEMANA, resumo_mod.ATUAL),
    ("Semana passada", resumo_mod.SEMANA, resumo_mod.ANTERIOR),
    ("Esta quinzena", resumo_mod.QUINZENA, resumo_mod.ATUAL),
    ("Quinzena passada", resumo_mod.QUINZENA, resumo_mod.ANTERIOR),
    ("Este mês", resumo_mod.MES, resumo_mod.ATUAL),
    ("Mês passado", resumo_mod.MES, resumo_mod.ANTERIOR),
]


def _qdate(dia: date) -> QDate:
    return QDate(dia.year, dia.month, dia.day)


def _date(dia: QDate) -> date:
    return date(dia.year(), dia.month(), dia.day())


class ResumoPorVendedorDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, hoje: date | None = None):
        super().__init__(parent)
        self._hoje = hoje or date.today()
        self._preenchendo = False
        self._texto = ""
        self._vendas = 0
        self.setWindowTitle("Resumo por vendedor")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        layout.addWidget(self._rotulo("Vendedor"))
        self.vendedor = QComboBox()
        self.vendedor.addItem(TODOS, None)
        for nome in vendedores_mod.listar_vendedores():
            self.vendedor.addItem(nome, nome)
        layout.addWidget(self.vendedor)

        layout.addWidget(self._rotulo("Período"))
        self.sugestao = QComboBox()
        for rotulo, tipo, qual in SUGESTOES:
            self.sugestao.addItem(rotulo, (tipo, qual))
        self.sugestao.addItem(PERSONALIZADO, None)
        layout.addWidget(self.sugestao)
        datas = QHBoxLayout()
        layout.addLayout(datas)
        datas.addWidget(QLabel("de"))
        self.de = self._campo_de_data()
        datas.addWidget(self.de)
        datas.addWidget(QLabel("até"))
        self.ate = self._campo_de_data()
        datas.addWidget(self.ate)
        datas.addStretch()

        layout.addWidget(self._rotulo("O que entra no resumo"))
        caixas = QHBoxLayout()
        layout.addLayout(caixas)
        self.caixas: dict[str, QCheckBox] = {}
        for bloco in resumo_mod.BLOCOS:
            caixa = QCheckBox(resumo_mod.TITULO_DO_BLOCO[bloco])
            caixa.setChecked(True)
            caixa.toggled.connect(lambda _=False: self._atualizar())
            caixas.addWidget(caixa)
            self.caixas[bloco] = caixa

        layout.addWidget(self._rotulo("Prévia"))
        self.previa = QPlainTextEdit()
        self.previa.setReadOnly(True)
        self.previa.setMinimumHeight(240)
        layout.addWidget(self.previa)

        self.aviso = QLabel("")
        self.aviso.setProperty("role", "secundario")
        self.aviso.setWordWrap(True)
        layout.addWidget(self.aviso)

        rodape = QHBoxLayout()
        layout.addLayout(rodape)
        rodape.addStretch()
        self.botao_fechar = QPushButton("Fechar")
        self.botao_fechar.clicked.connect(self.reject)
        rodape.addWidget(self.botao_fechar)
        self.botao_copiar = QPushButton("Copiar resumo")
        self.botao_copiar.setProperty("role", "botao_primario")
        self.botao_copiar.setDefault(True)
        self.botao_copiar.clicked.connect(self.copiar)
        rodape.addWidget(self.botao_copiar)

        self.vendedor.currentIndexChanged.connect(lambda *_: self._atualizar())
        self.sugestao.currentIndexChanged.connect(lambda *_: self._ao_escolher_sugestao())
        self.de.dateChanged.connect(lambda *_: self._ao_editar_datas())
        self.ate.dateChanged.connect(lambda *_: self._ao_editar_datas())
        self.sugestao.setCurrentIndex(0)  # Esta semana (segunda a domingo)
        self._ao_escolher_sugestao()

    # -- montagem -----------------------------------------------------------------------------------

    @staticmethod
    def _rotulo(texto: str) -> QLabel:
        rotulo = QLabel(texto)
        rotulo.setProperty("role", "secundario")
        return rotulo

    @staticmethod
    def _campo_de_data() -> QDateEdit:
        campo = QDateEdit()
        campo.setCalendarPopup(True)
        campo.setDisplayFormat("dd/MM/yyyy")
        return campo

    # -- periodo ------------------------------------------------------------------------------------

    def _ao_escolher_sugestao(self) -> None:
        escolha = self.sugestao.currentData()
        if escolha is not None:  # "Personalizado" nao preenche nada: so deixa as datas como estao
            tipo, qual = escolha
            per = resumo_mod.periodo(tipo, qual, self._hoje)
            self._preenchendo = True
            try:
                self.de.setDate(_qdate(per.inicio))
                self.ate.setDate(_qdate(per.fim))
            finally:
                self._preenchendo = False
        self._atualizar()

    def _ao_editar_datas(self) -> None:
        if self._preenchendo:
            return
        self.sugestao.blockSignals(True)  # editou a mao: o periodo e "Personalizado"
        self.sugestao.setCurrentIndex(self.sugestao.count() - 1)
        self.sugestao.blockSignals(False)
        self._atualizar()

    # -- previa e copia -----------------------------------------------------------------------------

    def blocos_marcados(self) -> list[str]:
        return [bloco for bloco, caixa in self.caixas.items() if caixa.isChecked()]

    def _atualizar(self) -> None:
        """Monta a previa com o que esta na tela; nunca falha em silencio (a mensagem aparece no aviso)."""
        self._texto = ""
        self.aviso.setText("")
        self.botao_copiar.setEnabled(False)
        if not self.blocos_marcados():
            self.previa.setPlainText("Marque pelo menos um bloco para o resumo.")
            return
        try:
            per = resumo_mod.periodo_das_datas(_date(self.de.date()), _date(self.ate.date()), self._hoje)
            resumo = resumo_mod.montar_resumo(per, self.vendedor.currentData(), self._hoje, self.blocos_marcados())
            texto = resumo_mod.texto_whatsapp(resumo)
        except resumo_mod.ErroResumo as exc:
            self.previa.setPlainText(str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            self.previa.setPlainText(f"Não foi possível montar o resumo: {type(exc).__name__}: {exc}")
            return
        self.previa.setPlainText(texto)
        if not resumo.vazio:
            self._texto = texto
            self._vendas = resumo.total
            self.botao_copiar.setEnabled(True)

    def copiar(self) -> bool:
        if not self._texto:
            return False
        QApplication.clipboard().setText(self._texto)
        n = self._vendas
        self.aviso.setText(f"Resumo copiado ({n} venda{'s' if n != 1 else ''}).")
        return True
