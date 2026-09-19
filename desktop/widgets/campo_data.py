"""Campo de data que aceita DIGITACAO direta (dd/mm/aaaa, com as barras
entrando sozinhas) e tambem um calendario, como alternativa.

Existe porque o QDateEdit do Qt, quando usado com "valor especial" pra
representar "nao informado" (como o Nascimento do cliente precisa), bloqueia
a digitacao ate a pessoa mexer nas setinhas/calendario. Um campo de texto com
mascara resolve: digitar, colar ("15/03/1985") ou escolher no calendario, e
vazio = "nao informado".
"""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QCalendarWidget, QHBoxLayout, QLineEdit, QMenu, QPushButton, QWidget, QWidgetAction

from desktop.widgets.formatters import conectar_mascara, formatar_data_parcial

_FORMATO = "dd/MM/yyyy"
_DATA_MINIMA = QDate(1900, 1, 1)
_TAMANHO_COMPLETO = len("dd/mm/aaaa")


class CampoData(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.campo = QLineEdit()
        self.campo.setPlaceholderText("dd/mm/aaaa")
        conectar_mascara(self.campo, formatar_data_parcial)
        self.campo.textChanged.connect(self._marcar_invalido_se_completo)
        layout.addWidget(self.campo, stretch=1)

        self._botao_calendario = QPushButton("📅")
        self._botao_calendario.setProperty("role", "botao_icone")
        self._botao_calendario.setToolTip("Escolher no calendário")
        self._botao_calendario.setAutoDefault(False)  # Enter no campo nao pode abrir o calendario
        self._botao_calendario.clicked.connect(self._abrir_calendario)
        layout.addWidget(self._botao_calendario)

        self._calendario = QCalendarWidget()
        self._calendario.setMinimumDate(_DATA_MINIMA)
        self._calendario.setMaximumDate(QDate.currentDate())
        self._calendario.clicked.connect(self._data_escolhida_no_calendario)
        # o calendario mora dentro de um menu-popup: fecha sozinho ao clicar
        # fora, sem precisar de um dialogo proprio
        self._menu = QMenu(self)
        acao = QWidgetAction(self._menu)
        acao.setDefaultWidget(self._calendario)
        self._menu.addAction(acao)

    # -- API ---------------------------------------------------------------------

    def texto(self) -> str:
        return self.campo.text().strip()

    def definir_data(self, data: QDate | None) -> None:
        self.campo.setText(data.toString(_FORMATO) if data is not None and data.isValid() else "")

    def avaliar(self) -> tuple[QDate | None, str]:
        """(data, "") se estiver em branco (data=None, "nao informado") ou for
        uma data valida; (None, mensagem) se o texto nao for uma data aceitavel."""
        texto = self.texto()
        if not texto:
            return None, ""
        if len(texto) < _TAMANHO_COMPLETO:
            return None, "Data incompleta - digite no formato dd/mm/aaaa (ex.: 15/03/1985)."
        data = QDate.fromString(texto, _FORMATO)
        if not data.isValid():
            return None, f"'{texto}' não é uma data válida - use o formato dd/mm/aaaa (ex.: 15/03/1985)."
        if data < _DATA_MINIMA:
            return None, "A data não pode ser anterior a 1900."
        if data > QDate.currentDate():
            return None, "A data não pode estar no futuro."
        return data, ""

    # -- internos ----------------------------------------------------------------

    def _marcar_invalido_se_completo(self, _texto: str) -> None:
        """Borda vermelha so quando o texto ja esta completo (10 caracteres) e
        mesmo assim invalido - enquanto digita, "1" ou "15/0" nao sao erro."""
        completo = len(self.texto()) >= _TAMANHO_COMPLETO
        invalido = completo and bool(self.avaliar()[1])
        self.campo.setProperty("invalido", invalido)
        self.campo.style().unpolish(self.campo)
        self.campo.style().polish(self.campo)

    def _abrir_calendario(self) -> None:
        atual, _ = self.avaliar()
        if atual is not None:
            self._calendario.setSelectedDate(atual)
        self._menu.popup(self._botao_calendario.mapToGlobal(self._botao_calendario.rect().bottomLeft()))

    def _data_escolhida_no_calendario(self, data: QDate) -> None:
        self.definir_data(data)
        self._menu.close()
        self.campo.setFocus()
