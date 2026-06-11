import pandas as pd
import numpy as np
import json


class Palpites:
    def __init__(self) -> None:
        self.palpites_com_placar = None

    def get_palpites(self):
        with open('resultados.json', encoding='utf-8') as file:
            self.resultados_jogos = json.load(file)
        self.palpites = pd.concat(
            pd.read_excel("Bolão Copa 2026.xlsm", sheet_name=None, engine='calamine')
        ).reset_index(level=0, names=['Palpite'])

        self.palpites['Data'] = self.palpites['Data'] + ' ' + self.palpites['Horário']
        self.palpites['Data'] = pd.to_datetime(self.palpites['Data'], format='%d/%m/%Y %H:%M')
        self.palpites = self.palpites[~self.palpites['Palpite'].isin(['Ranking','Layout Compartilhável', 'Macro Palpite'])]
        self.palpites['key'] = self.palpites['Data'].dt.strftime('%Y%m%d_%H%M') + '_' + self.palpites['Mandante'] + '_' + self.palpites['Visitante']

        self.palpites = self.palpites[self.palpites['key'].notna()]

        self.palpites = self.palpites[['Palpite', 'Data', 'Mandante', 'Placar Mandante', 'Placar Visitante','Visitante',  'key']]
        self.realizado = self.palpites[self.palpites['Palpite'] == 'Resultado Real']
        self.palpites = self.palpites[self.palpites['Palpite'] != 'Resultado Real']
        self.palpites['Placar Mandante'] = self.palpites['Placar Mandante'].fillna(0)
        self.palpites['Placar Visitante'] = self.palpites['Placar Visitante'].fillna(0)
        self.palpites['Placar Mandante'] = self.palpites['Placar Mandante'].astype(int)
        self.palpites['Placar Visitante'] = self.palpites['Placar Visitante'].astype(int)

        self.palpites['Ganhador'] = np.select(
            [self.palpites['Placar Mandante'] > self.palpites['Placar Visitante'],
            self.palpites['Placar Mandante'] == self.palpites['Placar Visitante'],
            self.palpites['Placar Mandante'] < self.palpites['Placar Visitante']],
            ['Mandante', 'Empate', 'Visitante'],
            ''
        )
        self.realizado['Placar Mandante'] = self.realizado['key'].map(self.resultados_jogos).str.get('Mandante')
        self.realizado['Placar Visitante'] = self.realizado['key'].map(self.resultados_jogos).str.get('Visitante')

        self.realizado_placar = self.realizado[(self.realizado['Placar Mandante'].notna()) & (self.realizado['Placar Visitante'].notna())].copy()

        self.realizado_placar['Placar Mandante'] = self.realizado_placar['Placar Mandante'].astype(int)
        self.realizado_placar['Placar Visitante'] = self.realizado_placar['Placar Visitante'].astype(int)

        self.realizado_placar['Ganhador'] = np.select(
            [self.realizado_placar['Placar Mandante'] > self.realizado_placar['Placar Visitante'],
            self.realizado_placar['Placar Mandante'] == self.realizado_placar['Placar Visitante'],
            self.realizado_placar['Placar Mandante'] < self.realizado_placar['Placar Visitante']],
            ['Mandante', 'Empate', 'Visitante'],
            ''

        )

        self.palpites_com_placar = self.palpites.merge(
            self.realizado_placar[['key', 'Placar Mandante', 'Placar Visitante', 'Ganhador']],
            on='key',
            suffixes=('', '_realizado'),
            how='left'
        )

        self.palpites_com_placar['Pontos'] = np.select(
            [(self.palpites_com_placar['Placar Mandante'] == self.palpites_com_placar['Placar Mandante_realizado']) & (self.palpites_com_placar['Placar Visitante'] == self.palpites_com_placar['Placar Visitante_realizado']),
            self.palpites_com_placar['Ganhador'] == self.palpites_com_placar['Ganhador_realizado']],
            [3, 1],
            0
        )

        self.palpites_com_placar['PontosAcm'] = self.palpites_com_placar.groupby('Palpite')['Pontos'].transform('cumsum')

        return self.palpites_com_placar

    def get_palpites_dia(self, acumulado=False):
        if self.palpites_com_placar is None:
            self.get_palpites()

        if acumulado:
            placar_dia_acumulado = self.palpites_com_placar[self.palpites_com_placar['Ganhador_realizado'].notna()].groupby(['Palpite', 'Data'])['PontosAcm'].sum().unstack(level=0)
            return placar_dia_acumulado

        placar_dia = self.palpites_com_placar[self.palpites_com_placar['Ganhador_realizado'].notna()].groupby(['Palpite', 'Data'])['Pontos'].sum().unstack(level=0)

        return placar_dia

    def get_points(self):
        if self.palpites_com_placar is None:
            self.get_palpites()

        resumo_pontos = self.palpites_com_placar.groupby('Palpite')[['Pontos']].sum().sort_values('Pontos', ascending=False)
        return resumo_pontos
