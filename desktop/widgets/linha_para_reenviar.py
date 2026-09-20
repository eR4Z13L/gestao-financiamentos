"""Uma linha de "Para reenviar": o cliente (clicavel: abre a ficha dele), em quais bancos as propostas foram
negadas, os bancos que ainda nao tentou e o botao "Duplicar", que abre a ficha com o card "Nova proposta"
ja preenchido a partir da mais recente. So o ADMIN cria proposta: a tela nem monta esta lista pro vendedor.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.dashboard import ClienteParaReenviar

_MAXIMO_DE_SUGESTOES = 4  # dos bancos que faltam, mostra estes e "+N"


def _lista(bancos: tuple[str, ...], maximo: int | None = None) -> str:
    if maximo is not None and len(bancos) > maximo:
        return ", ".join(bancos[:maximo]) + f" +{len(bancos) - maximo}"
    return ", ".join(bancos)


class LinhaParaReenviar(QWidget):
    duplicar_pedido = Signal(str, int)  # cpf, posicao real da proposta de onde duplicar
    ficha_pedida = Signal(str)  # cpf

    def __init__(self, item: ClienteParaReenviar, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "transparente")
        self._item = item

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(12)

        coluna = QVBoxLayout()
        coluna.setSpacing(1)
        self._botao_cliente = QPushButton(item.cliente or f"(sem cadastro) {item.cpf}")
        self._botao_cliente.setProperty("role", "botao_link")
        self._botao_cliente.setCursor(Qt.CursorShape.PointingHandCursor)
        self._botao_cliente.setEnabled(item.cadastrado)
        self._botao_cliente.setToolTip("Abrir a ficha do cliente" if item.cadastrado else "Há propostas com este CPF, mas nenhum cliente cadastrado")
        self._botao_cliente.clicked.connect(lambda: self.ficha_pedida.emit(item.cpf))
        coluna.addWidget(self._botao_cliente, alignment=Qt.AlignmentFlag.AlignLeft)

        n = item.propostas
        tentados = _lista(item.bancos_tentados)
        negadas = f"{n} proposta{'s' if n > 1 else ''} negada{'s' if n > 1 else ''}" + (f" · {tentados}" if tentados else "")
        self._negadas = QLabel(negadas)
        self._negadas.setProperty("role", "secundario")
        coluna.addWidget(self._negadas)

        sugestoes = _lista(item.bancos_nao_tentados, _MAXIMO_DE_SUGESTOES)
        self._sugestoes = QLabel(f"Ainda não tentou: {sugestoes}" if sugestoes else "Já tentou todos os bancos conhecidos")
        self._sugestoes.setProperty("role", "secundario")
        self._sugestoes.setToolTip(_lista(item.bancos_nao_tentados))
        coluna.addWidget(self._sugestoes)
        layout.addLayout(coluna, stretch=1)

        self._botao_duplicar = QPushButton("Duplicar")
        self._botao_duplicar.setProperty("role", "botao_primario")
        self._botao_duplicar.setEnabled(item.cadastrado)
        self._botao_duplicar.setToolTip(
            "Abre a ficha com uma nova proposta parecida com a mais recente (sem banco), pronta para escolher outro banco"
            if item.cadastrado
            else "Não dá para duplicar: este CPF não tem cliente cadastrado"
        )
        self._botao_duplicar.clicked.connect(lambda: self.duplicar_pedido.emit(item.cpf, item.indice_da_proposta))
        layout.addWidget(self._botao_duplicar, alignment=Qt.AlignmentFlag.AlignVCenter)

    def item(self) -> ClienteParaReenviar:
        return self._item

    def botao_duplicar(self) -> QPushButton:
        return self._botao_duplicar

    def botao_cliente(self) -> QPushButton:
        return self._botao_cliente

    def texto_das_negadas(self) -> str:
        return self._negadas.text()

    def texto_das_sugestoes(self) -> str:
        return self._sugestoes.text()
