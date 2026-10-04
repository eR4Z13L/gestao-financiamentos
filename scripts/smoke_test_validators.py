"""Testa core/validators.py: o que é aceito como CPF/CNPJ válido (dígito verificador, todos os dígitos
iguais, tamanho, vazio), a escolha CPF x CNPJ pelo tamanho, a máscara de formatar_cpf_cnpj, apenas_digitos
e a checagem simples de e-mail. Não precisa de Qt nem de arquivo nenhum.

Todos os números de CPF/CNPJ são FICTÍCIOS: exemplos de teste (529.982.247-25 já é usado no projeto) ou
gerados aqui mesmo pelo algoritmo, a partir de sementes fixas. Nenhum dado de pessoa real.

Os dígitos verificadores são conferidos contra uma implementação de REFERÊNCIA escrita aqui, de forma
independente (a fórmula "de livro": resto < 2 vira 0, senão 11 - resto), pra que um erro no cálculo de
core/validators.py não seja "confirmado" por ele mesmo.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_validators.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.validators import (
    _digito_verificador_cnpj,
    _digito_verificador_cpf,
    apenas_digitos,
    cnpj_valido,
    cpf_cnpj_valido,
    cpf_valido,
    email_valido,
    formatar_cpf_cnpj,
)

# CPFs fictícios. Dois deles caem no caso especial do código ("resto == 10 vira 0"), um em cada dígito.
CPF_PROJETO = "529.982.247-25"  # o CPF de teste que o projeto já usa
CPF_RESTO_10_NO_D1 = "123.456.789-09"
CPF_RESTO_10_NO_D2 = "987.654.321-00"
CPF_EXEMPLO = "111.444.777-35"
CPFS_VALIDOS = [CPF_PROJETO, CPF_RESTO_10_NO_D1, CPF_RESTO_10_NO_D2, CPF_EXEMPLO]

# CNPJs fictícios, escolhidos pelos casos de borda do "0 if resto < 2 else 11 - resto".
CNPJS_VALIDOS = {
    "11.222.333/0001-81": "2º dígito com resto 10 -> 11 - 10 = 1",
    "12.345.678/0001-95": "1º dígito com resto 2 -> 11 - 2 = 9 (logo acima da borda)",
    "20.000.000/0001-07": "1º dígito com resto 1 -> 0 (na borda)",
    "40.000.000/0001-06": "1º dígito com resto 0 -> 0",
    "60.000.000/0001-13": "1º dígito com resto 10 -> 11 - 10 = 1",
    "50.000.000/0001-60": "2º dígito com resto 1 -> 0 (na borda)",
}

PESOS_CPF_D1 = [10, 9, 8, 7, 6, 5, 4, 3, 2]
PESOS_CPF_D2 = [11, 10, 9, 8, 7, 6, 5, 4, 3, 2]
PESOS_CNPJ_D1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
PESOS_CNPJ_D2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _digito_referencia(numeros: list[int], pesos: list[int]) -> int:
    resto = sum(n * p for n, p in zip(numeros, pesos, strict=True)) % 11
    return 0 if resto < 2 else 11 - resto


def _dv_cpf_referencia(base9: str) -> str:
    numeros = [int(c) for c in base9]
    d1 = _digito_referencia(numeros, PESOS_CPF_D1)
    d2 = _digito_referencia(numeros + [d1], PESOS_CPF_D2)
    return f"{d1}{d2}"


def _dv_cnpj_referencia(base12: str) -> str:
    numeros = [int(c) for c in base12]
    d1 = _digito_referencia(numeros, PESOS_CNPJ_D1)
    d2 = _digito_referencia(numeros + [d1], PESOS_CNPJ_D2)
    return f"{d1}{d2}"


def _trocar_dv(numero: str, dv_novo: str) -> str:
    """Troca os 2 últimos dígitos (o verificador) mantendo a máscara, se houver."""
    return numero[:-2] + dv_novo


def _outros_dvs(dv_certo: str) -> list[str]:
    return [f"{i:02d}" for i in range(100) if f"{i:02d}" != dv_certo]


def testar_apenas_digitos() -> None:
    linha("1) apenas_digitos: tira tudo que não é dígito")
    casos = {
        "529.982.247-25": "52998224725",
        "11.222.333/0001-81": "11222333000181",
        "  529 982 247 25  ": "52998224725",
        "(41) 99999-0000": "41999990000",
        "abc": "",
        "": "",
        None: "",
    }
    for entrada, esperado in casos.items():
        obtido = apenas_digitos(entrada)
        assert obtido == esperado, f"apenas_digitos({entrada!r}) = {obtido!r}, esperado {esperado!r}"
    print(f"OK: {len(casos)} entradas (com máscara, espaços, letras, vazio e None) reduzidas só aos dígitos.")


def testar_cpf_valido() -> None:
    linha("2) CPF válido: com e sem máscara, com espaços em volta")
    for cpf in CPFS_VALIDOS:
        sem_mascara = apenas_digitos(cpf)
        assert cpf_valido(cpf), f"CPF com máscara deveria ser válido: {cpf}"
        assert cpf_valido(sem_mascara), f"CPF sem máscara deveria ser válido: {sem_mascara}"
        assert cpf_valido(f"  {cpf}  "), f"CPF com espaços em volta deveria ser válido: {cpf!r}"
        assert sem_mascara[9:] == _dv_cpf_referencia(sem_mascara[:9]), f"exemplo errado no próprio teste: {cpf}"
    print(f"OK: {len(CPFS_VALIDOS)} CPFs fictícios aceitos com máscara, sem máscara e com espaços.")
    print("OK: inclui os casos de borda em que o resto 10 vira dígito 0 (no 1º e no 2º verificador).")


def testar_cpf_digito_errado() -> None:
    linha("3) CPF com dígito verificador errado é recusado")
    for cpf in CPFS_VALIDOS:
        dv_certo = apenas_digitos(cpf)[9:]
        for dv in _outros_dvs(dv_certo):
            errado = _trocar_dv(cpf, dv)
            assert not cpf_valido(errado), f"CPF com dígito errado foi aceito: {errado} (o certo termina em {dv_certo})"
    print(f"OK: para cada um dos {len(CPFS_VALIDOS)} CPFs, as outras 99 terminações possíveis são recusadas.")

    # um dígito do meio trocado (erro de digitação comum) também tem que ser pego
    assert not cpf_valido("529.982.248-25")
    assert not cpf_valido("259.982.247-25")  # dois dígitos invertidos
    print("OK: trocar um dígito do meio ou inverter dois vizinhos também é recusado.")


def testar_cpf_todos_iguais() -> None:
    linha("4) CPF com todos os dígitos iguais (111.111.111-11 etc.) é recusado")
    for d in "0123456789":
        cpf = d * 11
        # Pelo cálculo do dígito, TODOS esses "passariam" (o verificador de ddd.ddd.ddd é dd):
        # quem os recusa é só a regra explícita "todos iguais" em cpf_valido.
        assert _digito_verificador_cpf(cpf) == d * 2, f"esperava que {cpf} batesse no cálculo do dígito"
        assert not cpf_valido(cpf), f"CPF com todos os dígitos iguais foi aceito: {cpf}"
        assert not cpf_valido(formatar_cpf_cnpj(cpf)), f"CPF com todos iguais (com máscara) foi aceito: {cpf}"
    print("OK: 000.000.000-00 a 999.999.999-99 recusados (com e sem máscara).")
    print("OK: confirmado que eles batem no cálculo do dígito - a recusa vem só da regra 'todos iguais'.")


def testar_cpf_tamanho_errado() -> None:
    linha("5) CPF com tamanho errado é recusado")
    base = apenas_digitos(CPF_PROJETO)
    casos = [
        base[:-1],  # 10 dígitos
        base[:9],  # só a base, sem verificador
        base + "0",  # 12 dígitos
        "0" + base,  # 12 dígitos, zero na frente
        base + base,  # 22 dígitos
        "5",
    ]
    for cpf in casos:
        assert not cpf_valido(cpf), f"CPF com {len(cpf)} dígitos foi aceito: {cpf}"
    print(f"OK: {len(casos)} tamanhos errados (1, 9, 10, 12 e 22 dígitos) recusados.")


def testar_vazio() -> None:
    linha("6) Vazio, None, espaços e texto sem dígitos: recusados sem dar erro")
    for valor in ("", None, "   ", "\t\n", "abc.def.ghi-jk", "...-/"):
        for funcao in (cpf_valido, cnpj_valido, cpf_cnpj_valido):
            assert funcao(valor) is False, f"{funcao.__name__}({valor!r}) deveria ser False"
    print("OK: cpf_valido, cnpj_valido e cpf_cnpj_valido devolvem False (sem exceção) para entradas vazias.")


def testar_cnpj_valido() -> None:
    linha("7) CNPJ válido: com e sem máscara, nos casos de borda do cálculo")
    for cnpj, borda in CNPJS_VALIDOS.items():
        sem_mascara = apenas_digitos(cnpj)
        assert sem_mascara[12:] == _dv_cnpj_referencia(sem_mascara[:12]), f"exemplo errado no próprio teste: {cnpj}"
        assert cnpj_valido(cnpj), f"CNPJ com máscara deveria ser válido: {cnpj} ({borda})"
        assert cnpj_valido(sem_mascara), f"CNPJ sem máscara deveria ser válido: {sem_mascara} ({borda})"
        assert cnpj_valido(f" {cnpj} "), f"CNPJ com espaços em volta deveria ser válido: {cnpj!r}"
        print(f"OK: {cnpj} aceito - {borda}.")


def testar_cnpj_digito_errado() -> None:
    linha("8) CNPJ com dígito verificador errado é recusado")
    for cnpj in CNPJS_VALIDOS:
        dv_certo = apenas_digitos(cnpj)[12:]
        for dv in _outros_dvs(dv_certo):
            errado = _trocar_dv(cnpj, dv)
            assert not cnpj_valido(errado), f"CNPJ com dígito errado foi aceito: {errado} (o certo termina em {dv_certo})"
    assert not cnpj_valido("11.222.333/0002-81"), "filial trocada sem refazer o dígito deveria ser recusada"
    print(f"OK: para cada um dos {len(CNPJS_VALIDOS)} CNPJs, as outras 99 terminações possíveis são recusadas.")
    print("OK: trocar a filial (0001 -> 0002) sem refazer o dígito também é recusado.")


def testar_cnpj_todos_iguais() -> None:
    linha("9) CNPJ com todos os dígitos iguais é recusado")
    for d in "0123456789":
        cnpj = d * 14
        assert not cnpj_valido(cnpj), f"CNPJ com todos os dígitos iguais foi aceito: {cnpj}"
        assert not cnpj_valido(formatar_cpf_cnpj(cnpj)), f"CNPJ com todos iguais (com máscara) foi aceito: {cnpj}"
    # Diferente do CPF, no CNPJ só o 00.000.000/0000-00 bate no cálculo do dígito; os outros já
    # cairiam pelo dígito. O de zeros depende da regra "todos iguais".
    assert _digito_verificador_cnpj("0" * 14) == "00"
    print("OK: 00.000.000/0000-00 a 99.999.999/9999-99 recusados (com e sem máscara).")


def testar_cnpj_tamanho_errado() -> None:
    linha("10) CNPJ com tamanho errado é recusado")
    base = apenas_digitos("11.222.333/0001-81")
    casos = [base[:-1], base[:12], base + "1", "0" + base, apenas_digitos(CPF_PROJETO)]
    for cnpj in casos:
        assert not cnpj_valido(cnpj), f"CNPJ com {len(cnpj)} dígitos foi aceito: {cnpj}"
    assert not cpf_valido("11.222.333/0001-81"), "um CNPJ não pode passar como CPF"
    print(f"OK: {len(casos)} tamanhos errados (11, 12, 13 e 15 dígitos) recusados; CPF não passa como CNPJ nem o contrário.")


def testar_contra_referencia() -> None:
    linha("11) Conferência em massa contra a implementação de referência")
    sorteio = random.Random(20261004)  # semente fixa: o teste é sempre o mesmo
    total_cpf = total_cnpj = 0
    for _ in range(300):
        base9 = "".join(sorteio.choice("0123456789") for _ in range(9))
        if base9 == base9[0] * 9:
            continue
        aceitos = [dv for dv in (f"{i:02d}" for i in range(100)) if cpf_valido(base9 + dv)]
        assert aceitos == [_dv_cpf_referencia(base9)], f"CPF base {base9}: aceitos {aceitos}, referência {_dv_cpf_referencia(base9)}"
        total_cpf += 1

        base12 = "".join(sorteio.choice("0123456789") for _ in range(12))
        if base12 == base12[0] * 12:
            continue
        aceitos = [dv for dv in (f"{i:02d}" for i in range(100)) if cnpj_valido(base12 + dv)]
        assert aceitos == [_dv_cnpj_referencia(base12)], f"CNPJ base {base12}: aceitos {aceitos}, referência {_dv_cnpj_referencia(base12)}"
        total_cnpj += 1
    print(f"OK: {total_cpf} bases de CPF e {total_cnpj} de CNPJ sorteadas: para cada uma, das 100 terminações")
    print("    possíveis só UMA é aceita, e é exatamente a da referência.")


def testar_cpf_cnpj_valido() -> None:
    linha("12) cpf_cnpj_valido escolhe CPF ou CNPJ pelo número de dígitos")
    for cpf in CPFS_VALIDOS:
        assert cpf_cnpj_valido(cpf) and cpf_cnpj_valido(apenas_digitos(cpf)), f"CPF válido recusado: {cpf}"
    for cnpj in CNPJS_VALIDOS:
        assert cpf_cnpj_valido(cnpj) and cpf_cnpj_valido(apenas_digitos(cnpj)), f"CNPJ válido recusado: {cnpj}"
    print("OK: CPFs (11 dígitos) e CNPJs (14 dígitos) válidos aceitos, com e sem máscara.")

    assert not cpf_cnpj_valido(_trocar_dv(CPF_PROJETO, "26")), "CPF com dígito errado aceito"
    assert not cpf_cnpj_valido(_trocar_dv("11.222.333/0001-81", "82")), "CNPJ com dígito errado aceito"
    assert not cpf_cnpj_valido("1" * 11) and not cpf_cnpj_valido("0" * 14), "todos iguais aceitos"
    print("OK: dígito errado e todos iguais continuam recusados pelo cpf_cnpj_valido.")

    # 14 dígitos são sempre julgados como CNPJ: um CPF válido com 3 zeros na frente não passa
    # (não vira CPF de novo), e um CNPJ "cortado" para 11 dígitos não é julgado como CNPJ.
    cpf_com_zeros = "000" + apenas_digitos(CPF_PROJETO)
    assert cpf_cnpj_valido(cpf_com_zeros) == cnpj_valido(cpf_com_zeros), "14 dígitos deveriam ir para cnpj_valido"
    assert not cpf_cnpj_valido(cpf_com_zeros)
    print("OK: com 14 dígitos a decisão é a do cnpj_valido (CPF com zeros na frente não passa).")

    for tamanho in (0, 1, 9, 10, 12, 13, 15, 22):
        numero = ("52998224725118" * 2)[:tamanho]
        assert not cpf_cnpj_valido(numero), f"{tamanho} dígitos foram aceitos: {numero!r}"
    print("OK: qualquer tamanho diferente de 11 e 14 (0, 1, 9, 10, 12, 13, 15, 22) é recusado.")


def testar_formatar() -> None:
    linha("13) formatar_cpf_cnpj: máscara para 11 e 14 dígitos; o resto volta como veio")
    casos = {
        "52998224725": "529.982.247-25",
        "529.982.247-25": "529.982.247-25",  # já formatado: fica igual
        " 529 982 247 25 ": "529.982.247-25",
        "11222333000181": "11.222.333/0001-81",
        "11.222.333/0001-81": "11.222.333/0001-81",
        # formatar não valida: um CPF com dígito errado também ganha a máscara
        "52998224726": "529.982.247-26",
    }
    for entrada, esperado in casos.items():
        obtido = formatar_cpf_cnpj(entrada)
        assert obtido == esperado, f"formatar_cpf_cnpj({entrada!r}) = {obtido!r}, esperado {esperado!r}"
    print(f"OK: {len(casos)} entradas de 11/14 dígitos formatadas (com ou sem máscara, inclusive dígito errado).")

    # Outros tamanhos: devolve o texto ORIGINAL, sem mexer (nem tira a pontuação).
    for entrada in ("5299822472", "529.982.247-2", "529982247251", "1122233300018", "abc", "", "  "):
        obtido = formatar_cpf_cnpj(entrada)
        assert obtido == entrada, f"formatar_cpf_cnpj({entrada!r}) = {obtido!r}, devia voltar como veio"
    # Comportamento atual: None volta None (a anotação diz str, mas quem chama não quebra).
    assert formatar_cpf_cnpj(None) is None
    print("OK: 10, 12, 13 dígitos, texto sem dígitos, vazio e espaços voltam exatamente como vieram (None volta None).")


def testar_email() -> None:
    linha("14) email_valido: checagem simples algo@algo.algo")
    validos = [
        "fulano@dominio.com",
        "fulano.silva@dominio.com.br",
        "fulano+tag@dominio.com",
        "a@b.co",
        "  fulano@dominio.com  ",  # espaços em volta são ignorados
    ]
    invalidos = [
        "fulano",
        "fulano@",
        "@dominio.com",
        "fulano@dominio",  # sem ponto depois do @
        "fulano@.com",
        "fulano@dominio.",
        "fulano dominio.com",
        "ful ano@dominio.com",  # espaço no meio
        "fulano@@dominio.com",
        "fulano@dominio@outro.com",
        "fulano@dominio.com outro",
    ]
    for texto in validos:
        assert email_valido(texto), f"deveria ser válido: {texto!r}"
    print(f"OK: {len(validos)} e-mails válidos aceitos (inclusive com espaços em volta).")
    for texto in invalidos:
        assert not email_valido(texto), f"deveria ser inválido: {texto!r}"
    print(f"OK: {len(invalidos)} e-mails inválidos recusados.")
    for texto in ("", None, "   "):
        assert email_valido(texto) is False, f"vazio deveria ser False: {texto!r}"
    print("OK: vazio, None e só espaços dão False (sem exceção).")

    # Comportamento atual, de propósito permissivo ("só pega erro de digitação óbvio"): estes passam.
    # Se um dia a regra ficar mais rígida, é aqui que muda.
    for texto in ("fulano@dominio..com", "fulano@dominio.com.", "a@b.c"):
        assert email_valido(texto), f"hoje este é aceito (checagem simples): {texto!r}"
    print("OK: casos tolerados pela checagem simples (ponto duplo, ponto no fim, domínio de 1 letra) seguem aceitos.")


def testar_entradas_estranhas() -> None:
    linha("15) Entradas estranhas: letras no meio e dígitos não-ASCII")
    # Comportamento atual: tudo que não é dígito é ignorado, então letras/pontuação no meio não atrapalham.
    assert cpf_valido("CPF: 529x982y247z25")
    assert cnpj_valido("CNPJ 11 222 333 0001 81")
    print("OK: letras e pontuação no meio são ignoradas (só os dígitos contam).")

    # Dígitos "de largura total" (５２９...) contam como dígito no Python, mas não batem com o
    # verificador calculado em ASCII - resultado: recusados. Bom: não entra CPF com caractere esquisito.
    largura_total = "".join(chr(ord(c) - ord("0") + 0xFF10) for c in "52998224725")
    assert not cpf_valido(largura_total)
    assert not cpf_cnpj_valido(largura_total)
    print("OK: CPF digitado com dígitos de largura total (５２９...) é recusado.")


def main() -> None:
    testar_apenas_digitos()
    testar_cpf_valido()
    testar_cpf_digito_errado()
    testar_cpf_todos_iguais()
    testar_cpf_tamanho_errado()
    testar_vazio()
    testar_cnpj_valido()
    testar_cnpj_digito_errado()
    testar_cnpj_todos_iguais()
    testar_cnpj_tamanho_errado()
    testar_contra_referencia()
    testar_cpf_cnpj_valido()
    testar_formatar()
    testar_email()
    testar_entradas_estranhas()
    linha("TUDO OK")


if __name__ == "__main__":
    main()
