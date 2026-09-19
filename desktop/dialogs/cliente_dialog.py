"""Dialogo de cadastro/edicao de cliente.

O mesmo formulario serve pros dois casos: passe cliente=None pra cadastrar
um novo, ou um dict (do jeito que core.clientes.buscar_por_cpf devolve) pra
editar um existente.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QDate
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import clientes as clientes_mod
from core import data_store as bd
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from core.endereco import UFS_VALIDAS
from core.validators import email_valido
from desktop.widgets.campo_data import CampoData
from desktop.widgets.formatters import (
    conectar_mascara,
    formatar_cep_parcial,
    formatar_cpf_cnpj_parcial,
    formatar_telefone_parcial,
)


class ClienteDialog(QDialog):
    def __init__(self, cliente: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._cliente_original = cliente
        self.cpf_salvo: str | None = None

        self.setWindowTitle("Editar cliente" if cliente else "Cadastrar novo cliente")
        self.setMinimumWidth(480)

        # o formulario tem muitas linhas: fica numa area rolavel, com OK/Cancelar
        # sempre visiveis embaixo - em tela pequena (ex.: notebook 1366x768) a
        # janela nao passa da tela e os botoes nunca ficam inalcancaveis
        raiz = QVBoxLayout(self)
        conteudo = QWidget()
        layout = QFormLayout(conteudo)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        rolagem.setWidget(conteudo)
        raiz.addWidget(rolagem, stretch=1)

        self._cpf = QLineEdit(cliente.get("CPF/CNPJ", "") if cliente else "")
        conectar_mascara(self._cpf, formatar_cpf_cnpj_parcial)
        layout.addRow("CPF/CNPJ *", self._cpf)

        self._nome = QLineEdit(cliente.get("CLIENTE", "") if cliente else "")
        layout.addRow("Nome completo *", self._nome)

        # logo abaixo do nome/CPF, junto das informacoes principais (e nao no
        # fim do formulario, com os campos secundarios)
        self._nascimento = CampoData()
        nascimento_atual = cliente.get("NASCIMENTO") if cliente else None
        if isinstance(nascimento_atual, pd.Timestamp) and not pd.isna(nascimento_atual):
            self._nascimento.definir_data(QDate(nascimento_atual.year, nascimento_atual.month, nascimento_atual.day))
        layout.addRow("Nascimento", self._nascimento)

        self._tipo = QComboBox()
        self._tipo.addItems(clientes_mod.TIPO_OPCOES)
        tipo_atual = (cliente.get("TIPO") or "").strip() if cliente else ""
        if tipo_atual:
            # compara sem diferenciar maiusculas/minusculas - um cliente
            # antigo salvo como "AVALISTA" precisa continuar marcado como
            # Avalista na edicao, nunca voltar silenciosamente pro primeiro
            # item ("Cliente") so por causa da grafia diferente.
            correspondente = next(
                (op for op in clientes_mod.TIPO_OPCOES if op.upper() == tipo_atual.upper()), None
            )
            if correspondente:
                self._tipo.setCurrentText(correspondente)
            else:
                # valor fora do padrao (ex: editado direto no Excel) - mostra
                # como esta, em vez de trocar pro primeiro item sem avisar
                self._tipo.addItem(tipo_atual)
                self._tipo.setCurrentText(tipo_atual)
        layout.addRow("Tipo *", self._tipo)

        vendedor_linha = QWidget()
        vendedor_layout = QHBoxLayout(vendedor_linha)
        vendedor_layout.setContentsMargins(0, 0, 0, 0)
        vendedor_layout.setSpacing(6)

        # combo travado (nao editavel) - so aceita nomes do cadastro de
        # vendedores, pra nao criar "BRUNO" e "Bruno" como pessoas diferentes
        self._vendedor = QComboBox()
        self._vendedor.setEditable(False)
        self._recarregar_vendedores(cliente.get("VENDEDOR", "") if cliente else "")
        vendedor_layout.addWidget(self._vendedor, 1)

        botao_novo_vendedor = QPushButton("+ Novo Vendedor")
        botao_novo_vendedor.setProperty("role", "botao_primario")
        botao_novo_vendedor.clicked.connect(self._cadastrar_vendedor)
        vendedor_layout.addWidget(botao_novo_vendedor)

        layout.addRow("Vendedor responsável", vendedor_linha)

        self._celular = QLineEdit(cliente.get("CELULAR", "") if cliente else "")
        conectar_mascara(self._celular, formatar_telefone_parcial)
        layout.addRow("Celular", self._celular)

        self._email = QLineEdit(cliente.get("EMAIL", "") if cliente else "")
        self._email.textChanged.connect(self._validar_email_ao_vivo)
        layout.addRow("E-mail", self._email)

        self._cep = QLineEdit(cliente.get("CEP", "") if cliente else "")
        conectar_mascara(self._cep, formatar_cep_parcial)
        self._cep.setPlaceholderText("00000-000")
        layout.addRow("CEP", self._cep)

        self._logradouro = QLineEdit(cliente.get("LOGRADOURO", "") if cliente else "")
        layout.addRow("Logradouro", self._logradouro)

        self._numero = QLineEdit(cliente.get("NÚMERO", "") if cliente else "")
        layout.addRow("Número", self._numero)

        self._complemento = QLineEdit(cliente.get("COMPLEMENTO", "") if cliente else "")
        self._complemento.setPlaceholderText("apto, bloco, sala...")
        layout.addRow("Complemento", self._complemento)

        self._bairro = QLineEdit(cliente.get("BAIRRO", "") if cliente else "")
        layout.addRow("Bairro", self._bairro)

        self._cidade = QLineEdit(cliente.get("CIDADE", "") if cliente else "")
        layout.addRow("Cidade", self._cidade)

        # lista fechada de estados (nao texto livre): impede "Ceara"/"CR"/etc.
        self._uf = QComboBox()
        self._uf.addItem("")  # UF e opcional
        self._uf.addItems(sorted(UFS_VALIDAS))
        uf_atual = (cliente.get("UF", "") if cliente else "").strip().upper()
        if uf_atual and uf_atual not in UFS_VALIDAS:
            # valor fora do padrao (ex.: editado direto no Excel) - mostra como
            # esta em vez de trocar por vazio sem avisar; salvar recusa
            # (core/clientes.py) ate a pessoa escolher um estado valido
            self._uf.addItem(uf_atual)
        self._uf.setCurrentText(uf_atual)
        layout.addRow("UF", self._uf)

        # so aparece pra cliente cujo endereco antigo (texto corrido) a
        # migracao nao conseguiu separar com seguranca - o texto fica aqui pra
        # a pessoa preencher os campos acima e depois apagar este
        self._endereco_revisar: QLineEdit | None = None
        texto_revisar = cliente.get("ENDEREÇO (REVISAR)", "") if cliente else ""
        if texto_revisar:
            self._endereco_revisar = QLineEdit(texto_revisar)
            self._endereco_revisar.setToolTip(
                "Endereço como estava antes de ser separado em campos. Preencha CEP, Logradouro, "
                "Número, Bairro e Cidade acima e depois apague este texto."
            )
            layout.addRow("Endereço original (revisar)", self._endereco_revisar)

        self._rede_social = QLineEdit(cliente.get("REDE SOCIAL", "") if cliente else "")
        layout.addRow("Rede social", self._rede_social)

        self._vinculado = QLineEdit(cliente.get("VINCULADO", "") if cliente else "")
        layout.addRow("Vinculado a (se for avalista)", self._vinculado)

        self._nome_pai = QLineEdit(cliente.get("NOME DO PAI", "") if cliente else "")
        layout.addRow("Nome do pai", self._nome_pai)

        self._nome_mae = QLineEdit(cliente.get("NOME DA MÃE", "") if cliente else "")
        layout.addRow("Nome da mãe", self._nome_mae)

        self._profissao = QLineEdit(cliente.get("PROFISSÃO", "") if cliente else "")
        layout.addRow("Profissão", self._profissao)

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.accepted.connect(self._salvar)
        botoes.rejected.connect(self.reject)
        raiz.addWidget(botoes)

        # abre com o tamanho do formulario inteiro, mas nunca maior que a tela
        # (o resto fica na rolagem)
        tela = QGuiApplication.primaryScreen()
        altura_disponivel = tela.availableGeometry().height() if tela else 720
        altura_ideal = conteudo.sizeHint().height() + botoes.sizeHint().height() + 40
        self.resize(520, min(altura_ideal, int(altura_disponivel * 0.9)))

    def _recarregar_vendedores(self, selecionado: str = "") -> None:
        self._vendedor.blockSignals(True)
        self._vendedor.clear()
        self._vendedor.addItem("")  # vendedor e opcional - permite deixar em branco
        nomes = vendedores_mod.listar_vendedores()
        self._vendedor.addItems(nomes)
        if selecionado and selecionado.upper() not in {n.upper() for n in nomes}:
            # cliente antigo com um vendedor que nao esta (mais) cadastrado -
            # mostra o valor atual em vez de trocar silenciosamente pra vazio
            self._vendedor.addItem(selecionado)
        self._vendedor.setCurrentText(selecionado)
        self._vendedor.blockSignals(False)

    def _cadastrar_vendedor(self) -> None:
        nome, ok = QInputDialog.getText(self, "Novo vendedor", "Nome do vendedor:")
        if not ok:
            return
        try:
            nome_salvo = vendedores_mod.adicionar_vendedor(nome)
            senhas_geradas = vendedores_mod.gerar_senhas_iniciais_pendentes()
        except vendedores_mod.ErroVendedor as exc:
            QMessageBox.warning(self, "Não foi possível cadastrar", str(exc))
            return
        except sessao_mod.PermissaoNegada as exc:
            QMessageBox.warning(self, "Ação não permitida", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao cadastrar vendedor", str(exc))
            return
        self._recarregar_vendedores(nome_salvo)

        senha_do_novo = senhas_geradas.get(nome_salvo)
        if senha_do_novo:
            QMessageBox.information(
                self,
                "Senha inicial gerada",
                f"Senha inicial de acesso para '{nome_salvo}': {senha_do_novo}\n\n"
                "Anote/avise agora - essa senha não pode ser recuperada depois (só redefinida).",
            )

    def _validar_email_ao_vivo(self, texto: str) -> None:
        """So um aviso visual (borda vermelha) enquanto digita - quem
        realmente impede salvar com e-mail invalido e core.clientes."""
        valido = not texto.strip() or email_valido(texto)
        self._email.setProperty("invalido", not valido)
        self._email.style().unpolish(self._email)
        self._email.style().polish(self._email)

    def _salvar(self) -> None:
        # data invalida NUNCA vira "nao informado" em silencio - avisa e nao salva
        nascimento, erro_nascimento = self._nascimento.avaliar()
        if erro_nascimento:
            QMessageBox.warning(self, "Nascimento inválido", erro_nascimento)
            self._nascimento.campo.setFocus()
            return

        campos = {
            "CPF/CNPJ": self._cpf.text().strip(),
            "CLIENTE": self._nome.text().strip(),
            "TIPO": self._tipo.currentText(),
            "VENDEDOR": self._vendedor.currentText().strip(),
            "CELULAR": self._celular.text().strip(),
            "EMAIL": self._email.text().strip(),
            "REDE SOCIAL": self._rede_social.text().strip(),
            "VINCULADO": self._vinculado.text().strip(),
            "NASCIMENTO": pd.Timestamp(nascimento.year(), nascimento.month(), nascimento.day()) if nascimento else "",
            "CEP": self._cep.text().strip(),
            "LOGRADOURO": self._logradouro.text().strip(),
            "NÚMERO": self._numero.text().strip(),
            "COMPLEMENTO": self._complemento.text().strip(),
            "BAIRRO": self._bairro.text().strip(),
            "CIDADE": self._cidade.text().strip(),
            "UF": self._uf.currentText().strip(),
            "ENDEREÇO (REVISAR)": self._endereco_revisar.text().strip() if self._endereco_revisar else "",
            "NOME DO PAI": self._nome_pai.text().strip(),
            "NOME DA MÃE": self._nome_mae.text().strip(),
            "PROFISSÃO": self._profissao.text().strip(),
        }
        try:
            if self._cliente_original is None:
                clientes_mod.adicionar_cliente(campos)
            else:
                clientes_mod.atualizar_cliente(self._cliente_original["CPF/CNPJ"], campos)
        except clientes_mod.ErroCliente as exc:
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

        self.cpf_salvo = campos["CPF/CNPJ"]
        self.accept()
