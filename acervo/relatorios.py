"""Relatórios para baixar."""
import csv

from django.http import HttpResponse

# O Excel trata como fórmula uma célula que comece com um destes caracteres
INICIOS_DE_FORMULA = ('=', '+', '-', '@', '\t', '\r')

CABECALHO = ['Livro', 'Exemplar', 'Membro', 'Saída', 'Devolução prevista', 'Devolução', 'Multa', 'Multa paga']


def celula_segura(valor):
    """Um apóstrofo na frente faz a planilha mostrar o texto em vez de executá-lo."""
    texto = str(valor)
    return f"'{texto}" if texto.startswith(INICIOS_DE_FORMULA) else texto


def _data(valor):
    return valor.strftime('%d/%m/%Y') if valor else ''


def emprestimos_csv(emprestimos, nome_do_arquivo):
    # BOM e ponto e vírgula: o Excel em português abre com acentos e colunas certas
    resposta = HttpResponse(content_type='text/csv; charset=utf-8')
    resposta['Content-Disposition'] = f'attachment; filename="{nome_do_arquivo}"'
    resposta.write('\ufeff')  # uma única vez, no começo do arquivo
    escritor = csv.writer(resposta, delimiter=';')
    escritor.writerow(CABECALHO)
    for emprestimo in emprestimos:
        linha = [
            emprestimo.exemplar.livro.titulo,
            emprestimo.exemplar.codigo,
            emprestimo.membro.nome,
            _data(emprestimo.data_emprestimo),
            _data(emprestimo.data_prevista_devolucao),
            _data(emprestimo.data_devolucao),
            str(emprestimo.multa).replace('.', ','),
            'sim' if emprestimo.multa_paga else 'não',
        ]
        escritor.writerow([celula_segura(valor) for valor in linha])
    return resposta
