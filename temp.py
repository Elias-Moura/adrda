"""
Função que avalia o perfil e a corretora do cliente pega a respectiva carteira
e adiciona os ativos que o cliente não possui.
"""
from pandas import DataFrame
from functools import partial

CARTEIRAS = {
    'WARREN': {
        'CONSERVADOR': xl("'https://d.docs.live.net/46dabf9126479874/Area Tecnica/Área Técnica Exclusiva/1. Consultoria de Investimentos/!REBALANCEAMENTOS/[2. BALIZA_PARA_AUTOMATIZADA.xlsx]Planilha1'!$C$5:$E$35", headers=True),
        'MODERADO': xl("'https://d.docs.live.net/46dabf9126479874/Area Tecnica/Área Técnica Exclusiva/1. Consultoria de Investimentos/!REBALANCEAMENTOS/[2. BALIZA_PARA_AUTOMATIZADA.xlsx]Planilha1'!H5:J35", headers=True),
        'BALANCEADO': xl("'https://d.docs.live.net/46dabf9126479874/Area Tecnica/Área Técnica Exclusiva/1. Consultoria de Investimentos/!REBALANCEAMENTOS/[2. BALIZA_PARA_AUTOMATIZADA.xlsx]Planilha1'!M5:O35", headers=True),
        'ARROJADO': xl("'https://d.docs.live.net/46dabf9126479874/Area Tecnica/Área Técnica Exclusiva/1. Consultoria de Investimentos/!REBALANCEAMENTOS/[2. BALIZA_PARA_AUTOMATIZADA.xlsx]Planilha1'!R5:T35", headers=True),
        'AGRESSIVO': xl("'https://d.docs.live.net/46dabf9126479874/Area Tecnica/Área Técnica Exclusiva/1. Consultoria de Investimentos/!REBALANCEAMENTOS/[2. BALIZA_PARA_AUTOMATIZADA.xlsx]Planilha1'!W5:Y35", headers=True),
    },
    'XP': {
        'CONSERVADOR': xl("'https://d.docs.live.net/46dabf9126479874/Area Tecnica/Área Técnica Exclusiva/1. Consultoria de Investimentos/!REBALANCEAMENTOS/[2. BALIZA_PARA_AUTOMATIZADA.xlsx]Planilha1'!C41:E71", headers=True),
        'MODERADO': xl("'https://d.docs.live.net/46dabf9126479874/Area Tecnica/Área Técnica Exclusiva/1. Consultoria de Investimentos/!REBALANCEAMENTOS/[2. BALIZA_PARA_AUTOMATIZADA.xlsx]Planilha1'!H41:J71", headers=True),
        'BALANCEADO': xl("'https://d.docs.live.net/46dabf9126479874/Area Tecnica/Área Técnica Exclusiva/1. Consultoria de Investimentos/!REBALANCEAMENTOS/[2. BALIZA_PARA_AUTOMATIZADA.xlsx]Planilha1'!M41:O71", headers=True),
        'ARROJADO': xl("'https://d.docs.live.net/46dabf9126479874/Area Tecnica/Área Técnica Exclusiva/1. Consultoria de Investimentos/!REBALANCEAMENTOS/[2. BALIZA_PARA_AUTOMATIZADA.xlsx]Planilha1'!R41:T71", headers=True),
        'AGRESSIVO': xl("'https://d.docs.live.net/46dabf9126479874/Area Tecnica/Área Técnica Exclusiva/1. Consultoria de Investimentos/!REBALANCEAMENTOS/[2. BALIZA_PARA_AUTOMATIZADA.xlsx]Planilha1'!W41:Y71", headers=True),
    },
    'BTG': {
        'CONSERVADOR': xl("'https://d.docs.live.net/46dabf9126479874/Area Tecnica/Área Técnica Exclusiva/1. Consultoria de Investimentos/!REBALANCEAMENTOS/[2. BALIZA_PARA_AUTOMATIZADA.xlsx]Planilha1'!C77:E107", headers=True),
        'MODERADO': xl("'https://d.docs.live.net/46dabf9126479874/Area Tecnica/Área Técnica Exclusiva/1. Consultoria de Investimentos/!REBALANCEAMENTOS/[2. BALIZA_PARA_AUTOMATIZADA.xlsx]Planilha1'!H77:J107", headers=True),
        'BALANCEADO': xl("'https://d.docs.live.net/46dabf9126479874/Area Tecnica/Área Técnica Exclusiva/1. Consultoria de Investimentos/!REBALANCEAMENTOS/[2. BALIZA_PARA_AUTOMATIZADA.xlsx]Planilha1'!M77:O107", headers=True),
        'ARROJADO': xl("'https://d.docs.live.net/46dabf9126479874/Area Tecnica/Área Técnica Exclusiva/1. Consultoria de Investimentos/!REBALANCEAMENTOS/[2. BALIZA_PARA_AUTOMATIZADA.xlsx]Planilha1'!R77:T107", headers=True),
        'AGRESSIVO': xl("'https://d.docs.live.net/46dabf9126479874/Area Tecnica/Área Técnica Exclusiva/1. Consultoria de Investimentos/!REBALANCEAMENTOS/[2. BALIZA_PARA_AUTOMATIZADA.xlsx]Planilha1'!W77:Y107", headers=True),
    },
}

corretora = xl("REBALANCEADOR!$B$4")
perfil_de_investidor = xl("REBALANCEADOR!$B$6")
usar_fii = xl("REBALANCEADOR!B8") == "SIM"


def pegar_carteira(corretora: str, perfil_de_investidor: str) -> DataFrame:
    corretora_limpa = corretora.strip().upper()

    perfil_de_investidor = perfil_de_investidor.split('-')[1].strip().upper()

    #return CARTEIRAS[corretora_limpa][perfil_de_investidor].dropna()
    carteira_modelo = CARTEIRAS[corretora_limpa][perfil_de_investidor].dropna()
    
    if not usar_fii:
        carteira_modelo = remove_fii(carteira_modelo)

    return carteira_modelo

pegar_carteira_pronta = partial(pegar_carteira, corretora, perfil_de_investidor)