"""Cadastro de Equipamentos da tela Cadastros: a lista fechada do campo Equipamento da venda e da proposta (decidido
com o usuario em 03/10/2026 - equipamento novo so entra por aqui). As regras ficam em core/equipamentos.py; a tela e a
peca de cadastro em cards (desktop/widgets/cadastro_em_cards.py), aqui com varios campos (o card abre para baixo).

Em cima da lista, enquanto houver nomes usados em propostas e vendas que o cadastro ainda nao tem, um aviso com
"Trazer para o cadastro...": os nomes simples entram sozinhos; os que podem ser dois equipamentos num nome so
("Laser X e Cadeira Y") vao para o usuario decidir (TrazerEquipamentosDialog), nenhum marcado de inicio.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core.formatting import formatar_reais
from desktop.widgets.cadastro_em_cards import CadastroEmCards, Campo, DefinicaoDoCadastro, ItemDoCadastro

_CAMPOS = [  # (chave do formulario, coluna da planilha)
    ("nome", "EQUIPAMENTO"),
    ("fornecedor", "FORNECEDOR"),
    ("parcelas", "PARCELAS"),
    ("valor_parcela", "VALOR PARCELA (R$)"),
    ("referencia", "VALOR LÍQUIDO/REFERÊNCIA (R$)"),
    ("observacoes", "OBSERVAÇÕES"),
]
_NUMERICOS = {"PARCELAS", "VALOR PARCELA (R$)", "VALOR LÍQUIDO/REFERÊNCIA (R$)"}


def _texto(valor) -> str:
    if valor is None or valor == "" or (isinstance(valor, float) and valor != valor):
        return ""
    if isinstance(valor, float):
        return str(int(valor)) if valor.is_integer() else f"{valor:.2f}".replace(".", ",")
    return str(valor)


def _quantas(propostas: int) -> str:
    return "nenhuma proposta" if not propostas else f"{propostas} proposta" + ("" if propostas == 1 else "s")


def _listar() -> list[ItemDoCadastro]:
    df = equipamentos_mod.listar_cadastro()
    itens = []
    for _, linha in df.iterrows():
        partes = [linha["FORNECEDOR"] or "Sem fornecedor", _quantas(int(linha["PROPOSTAS"]))]
        if _texto(linha["VALOR LÍQUIDO/REFERÊNCIA (R$)"]):
            partes.insert(1, formatar_reais(linha["VALOR LÍQUIDO/REFERÊNCIA (R$)"]).replace(",00", ""))
        itens.append(ItemDoCadastro(
            chave=linha["EQUIPAMENTO"], titulo=linha["EQUIPAMENTO"], detalhe=" · ".join(partes), ativo=bool(linha["ATIVO"]),
            valores={chave: _texto(linha[coluna]) for chave, coluna in _CAMPOS}, busca=linha["OBSERVAÇÕES"],
        ))
    return itens


def _campos_da_planilha(valores: dict) -> dict:
    """O que foi digitado -> colunas da planilha; numeros aceitam "1.500,00" ou "1500.00"."""
    campos = {}
    for chave, coluna in _CAMPOS:
        if chave not in valores:
            continue
        valor = valores[chave].strip()
        if coluna in _NUMERICOS and valor:
            numero = propostas_mod._converter_valor(valor)
            if numero is None:
                rotulo = next(c.rotulo for c in _CAMPOS_DO_FORMULARIO if c.chave == chave)
                raise equipamentos_mod.ErroEquipamento(f"{rotulo}: use um número (ex.: 1500 ou 1.500,00).")
            valor = numero
        campos[coluna] = valor
    return campos


def _adicionar(valores: dict) -> str:
    nome = equipamentos_mod.cadastrar(_campos_da_planilha(valores))
    return f"'{nome}' já aparece nas listas da venda e da proposta."


def _salvar(nome: str, valores: dict) -> str:
    quantidade = equipamentos_mod.salvar(nome, _campos_da_planilha(valores))
    extra = f" {quantidade} proposta(s) também foram atualizadas com o nome novo." if quantidade else ""
    return f"Equipamento salvo.{extra}"


def _definir_ativo(nome: str, ativo: bool) -> str:
    equipamentos_mod.definir_ativo(nome, ativo)
    return f"'{nome}' {'voltou para' if ativo else 'não aparece mais'} nas listas da venda e da proposta."


def _excluir(nome: str) -> str:
    equipamentos_mod.excluir(nome)
    return f"'{nome}' foi apagado do cadastro."


_CAMPOS_DO_FORMULARIO = [
    Campo("nome", "Nome", obrigatorio=True, dica="Ex.: Laser Exemplo 3000"),
    Campo("fornecedor", "Fornecedor"),
    Campo("parcelas", "Parcelas", dica="Ex.: 48"),
    Campo("valor_parcela", "Valor da parcela (R$)", dica="Ex.: 2.150,00"),
    Campo("referencia", "Valor líquido/referência (R$)", dica="Ex.: 80.000,00"),
    Campo("observacoes", "Observações"),
]


def definicao_equipamentos() -> DefinicaoDoCadastro:
    return DefinicaoDoCadastro(
        titulo="Equipamentos",
        nome_do_item="equipamento",
        explicacao=(
            "A lista do campo Equipamento da venda e da proposta (o equipamento só é escolhido daqui). O lápis "
            "edita (trocar o nome muda também as propostas e vendas); os três pontinhos desativam (sai da lista, o "
            "que já foi lançado fica como está) ou excluem um que nenhuma proposta usa."
        ),
        campos=_CAMPOS_DO_FORMULARIO,
        listar=_listar,
        adicionar=_adicionar,
        salvar=_salvar,
        definir_ativo=_definir_ativo,
        excluir=_excluir,
        erros_esperados=(equipamentos_mod.ErroEquipamento,),
        pergunta_ao_desativar=lambda item: (
            f"Desativar '{item.titulo}'? Ele sai das listas da venda e da proposta; o que já foi lançado continua com ele."
        ),
    )


class TrazerEquipamentosDialog(QDialog):
    """Os nomes usados nas propostas que o cadastro ainda nao tem: os simples entram; os que podem ser dois
    equipamentos num nome so, o usuario decide (nada marcado de inicio; o botao so libera com tudo respondido)."""

    def __init__(self, simples: list[str], juntos: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.simples = simples
        self.resultado: dict | None = None
        self.setWindowTitle("Trazer os equipamentos das propostas para o cadastro")
        self.resize(640, 560)
        layout = QVBoxLayout(self)
        texto = QLabel(
            f"<b>{len(simples)} nome(s)</b> já usados nas propostas entram no cadastro como estão"
            + (f": {', '.join(simples)}." if simples else ".")
            + (f"<br><br><b>{len(juntos)} nome(s)</b> podem ser dois equipamentos digitados juntos. Para cada um, diga "
               "como fica (as propostas e vendas que o citam acompanham)." if juntos else "")
            + "<br><br>Um backup é feito antes de gravar."
        )
        texto.setWordWrap(True)
        layout.addWidget(texto)

        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        conteudo = QWidget()
        conteudo.setProperty("role", "transparente")
        lista = QVBoxLayout(conteudo)
        self.respostas: dict[str, tuple[QButtonGroup, QLineEdit]] = {}
        for nome in juntos:
            cartao = QFrame(conteudo)
            cartao.setProperty("role", "card")
            corpo = QVBoxLayout(cartao)
            titulo = QLabel(f"<b>{nome}</b>", cartao)
            corpo.addWidget(titulo)
            grupo = QButtonGroup(cartao)
            um = QRadioButton("É um equipamento só", cartao)
            varios = QRadioButton("São equipamentos diferentes (um por vírgula):", cartao)
            grupo.addButton(um, 1)
            grupo.addButton(varios, 2)
            partes = QLineEdit(_sugerir_partes(nome), cartao)
            partes.setEnabled(False)
            grupo.idClicked.connect(lambda i, campo=partes: (campo.setEnabled(i == 2), self._atualizar()))
            partes.textChanged.connect(self._atualizar)
            for w in (um, varios, partes):
                corpo.addWidget(w)
            self.respostas[nome] = (grupo, partes)
            lista.addWidget(cartao)
        lista.addStretch()
        rolagem.setWidget(conteudo)
        layout.addWidget(rolagem, stretch=1)

        self.falta = QLabel("")
        self.falta.setProperty("role", "secundario")
        layout.addWidget(self.falta)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        self.botao_trazer = botoes.button(QDialogButtonBox.StandardButton.Ok)
        self.botao_trazer.setText("Trazer para o cadastro")
        botoes.accepted.connect(self._trazer)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)
        self._atualizar()

    def decisoes(self) -> dict[str, list[str]]:
        """So as respondidas: nome -> [nome] (um so) ou as partes."""
        resultado = {}
        for nome, (grupo, partes) in self.respostas.items():
            if grupo.checkedId() == 1:
                resultado[nome] = [nome]
            elif grupo.checkedId() == 2:
                lista = [p.strip() for p in partes.text().split(",") if p.strip()]
                if lista:
                    resultado[nome] = lista
        return resultado

    def _atualizar(self, *_args) -> None:
        faltam = len(self.respostas) - len(self.decisoes())
        self.botao_trazer.setEnabled(faltam == 0)
        self.falta.setText(f"Falta decidir {faltam} nome(s)." if faltam else "Tudo decidido.")

    def _trazer(self) -> None:
        try:
            self.resultado = equipamentos_mod.trazer_para_o_cadastro(self.simples, self.decisoes())
        except equipamentos_mod.ErroEquipamento as exc:
            QMessageBox.warning(self, "Não foi possível trazer", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado", f"{type(exc).__name__}: {exc}")
            return
        r = self.resultado
        extra = f" {r['propostas_alteradas']} proposta(s) passaram a citar os equipamentos separados." \
            if r["propostas_alteradas"] else ""
        QMessageBox.information(self, "Equipamentos no cadastro",
                                f"{r['cadastrados']} equipamento(s) entraram no cadastro.{extra}\n\n"
                                f"O estado de antes foi guardado em:\n{r['backup']}")
        self.accept()


def _sugerir_partes(nome: str) -> str:
    """ "Laser X e Cadeira Y" -> "Laser X, Cadeira Y" (so a sugestao do campo: o usuario confere)."""
    texto = f" {nome} "
    for juntador in (" e ", " E ", "/", " & "):
        texto = texto.replace(juntador, ",")
    return ", ".join(p.strip() for p in texto.split(",") if p.strip())


class CadastroEquipamentos(CadastroEmCards):
    def __init__(self, parent: QWidget | None = None, *, dentro_de_pagina: bool = False):
        self.aviso_fora: QFrame | None = None
        super().__init__(definicao_equipamentos(), parent, dentro_de_pagina=dentro_de_pagina)
        self.aviso_fora = QFrame(self)
        self.aviso_fora.setProperty("role", "chip_filtro")
        linha = QHBoxLayout(self.aviso_fora)
        linha.setContentsMargins(12, 6, 8, 6)
        self.texto_fora = QLabel("", self.aviso_fora)
        self.texto_fora.setWordWrap(True)
        linha.addWidget(self.texto_fora, stretch=1)
        self.botao_trazer = QPushButton("Trazer para o cadastro…", self.aviso_fora)
        self.botao_trazer.clicked.connect(self.trazer)
        linha.addWidget(self.botao_trazer)
        self.layout().insertWidget(2, self.aviso_fora)  # depois do titulo e da explicacao
        self._atualizar_aviso()

    def recarregar(self) -> None:
        super().recarregar()
        if self.aviso_fora is not None:
            self._atualizar_aviso()

    def _atualizar_aviso(self) -> None:
        try:
            simples, juntos = equipamentos_mod.nomes_fora_do_cadastro()
        except Exception as exc:  # nunca falhar em silencio
            self.texto_fora.setText(f"Não foi possível conferir os equipamentos das propostas: {exc}")
            self.aviso_fora.setVisible(True)
            self.botao_trazer.setEnabled(False)
            return
        total = len(simples) + len(juntos)
        self.texto_fora.setText(
            f"{total} equipamento(s) usados nas propostas ainda não estão no cadastro"
            + (f" ({len(juntos)} para você decidir se são dois equipamentos num nome só)." if juntos else ".")
        )
        self.botao_trazer.setEnabled(True)
        self.aviso_fora.setVisible(total > 0)

    def trazer(self) -> bool:
        simples, juntos = equipamentos_mod.nomes_fora_do_cadastro()
        dialogo = TrazerEquipamentosDialog(simples, juntos, self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return False
        self.recarregar()
        self.alterado.emit()
        return True
