from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)

DEFAULT_EXCEL_PATH = Path("Bolão Copa 2026.xlsx")
DEFAULT_RESULTS_PATH = Path("resultados.json")
DEFAULT_EXCEL_ENGINE = "calamine"

EXCLUDED_SHEETS = frozenset(
    {
        "Resultado Real",
        "Ranking",
        "Layout Compartilhável",
        "Macro Palpite",
    }
)
REQUIRED_MATCH_COLUMNS = frozenset(
    {
        "Data",
        "Horário",
        "Mandante",
        "Placar Mandante",
        "Placar Visitante",
        "Visitante",
    }
)
SCORE_COLUMNS = ("Placar Mandante", "Placar Visitante")
OUTCOME_HOME = "Mandante"
OUTCOME_DRAW = "Empate"
OUTCOME_AWAY = "Visitante"
POINTS_EXACT_SCORE = 3
POINTS_OUTCOME = 1

ScoreValue = int | None
ResultsMapping = dict[str, dict[str, ScoreValue]]


@dataclass(frozen=True)
class BolaoConfig:
    """Configura os caminhos e motor de leitura usados no cálculo do bolão."""

    excel_path: Path = DEFAULT_EXCEL_PATH
    results_path: Path = DEFAULT_RESULTS_PATH
    excel_engine: str | None = DEFAULT_EXCEL_ENGINE


@dataclass(frozen=True)
class BolaoData:
    """Agrupa as tabelas principais geradas a partir da planilha e do JSON."""

    palpites: pd.DataFrame
    ranking: pd.DataFrame
    evolucao: pd.DataFrame
    resultados: pd.DataFrame


def configure_logging(level: int = logging.INFO) -> None:
    """Configura logging simples para execução direta do módulo."""

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def read_results_json(results_path: Path | str = DEFAULT_RESULTS_PATH) -> ResultsMapping:
    """Lê e valida o arquivo JSON com os placares oficiais.

    Args:
        results_path: Caminho do arquivo `resultados.json`.

    Returns:
        Dicionário no formato `{key: {"Mandante": int | None, "Visitante": int | None}}`.

    Raises:
        FileNotFoundError: Quando o JSON não existe.
        ValueError: Quando a estrutura ou algum placar é inválido.
    """

    path = Path(results_path)
    with path.open("r", encoding="utf-8") as file:
        raw_results = json.load(file)

    if not isinstance(raw_results, dict):
        raise ValueError("O arquivo de resultados deve conter um objeto JSON na raiz.")

    normalized_results: ResultsMapping = {}
    for key, score_payload in raw_results.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"Chave de jogo inválida no JSON: {key!r}")
        if not isinstance(score_payload, dict):
            raise ValueError(f"Resultado inválido para o jogo {key!r}: esperado objeto.")

        normalized_results[key] = {
            "Mandante": _normalize_score_value(score_payload.get("Mandante"), key),
            "Visitante": _normalize_score_value(score_payload.get("Visitante"), key),
        }

    return normalized_results


def write_results_json(
    results: ResultsMapping,
    results_path: Path | str = DEFAULT_RESULTS_PATH,
) -> None:
    """Persiste resultados no JSON com UTF-8 e indentação legível."""

    path = Path(results_path)
    with path.open("w", encoding="utf-8") as file:
        json.dump(results, file, ensure_ascii=False, indent=4)
        file.write("\n")


def load_bolao_data(config: BolaoConfig | None = None) -> BolaoData:
    """Carrega planilha e JSON, calcula pontuação, ranking e evolução acumulada."""

    resolved_config = config or BolaoConfig()
    sheets = read_excel_sheets(resolved_config.excel_path, resolved_config.excel_engine)
    raw_results = read_results_json(resolved_config.results_path)

    schedule = build_schedule_dataframe(sheets)
    predictions = build_predictions_dataframe(sheets)
    results = build_results_dataframe(raw_results, schedule)
    scored_predictions = score_predictions(predictions, results)

    return BolaoData(
        palpites=scored_predictions,
        ranking=build_ranking(scored_predictions),
        evolucao=build_points_evolution(scored_predictions),
        resultados=results,
    )


def read_excel_sheets(
    excel_path: Path | str = DEFAULT_EXCEL_PATH,
    excel_engine: str | None = DEFAULT_EXCEL_ENGINE,
) -> dict[str, pd.DataFrame]:
    """Lê todas as abas da planilha, usando `calamine` com fallback para `openpyxl`."""

    path = Path(excel_path)
    if not path.exists():
        raise FileNotFoundError(f"Planilha não encontrada: {path}")

    engines_to_try = _build_excel_engine_priority(excel_engine)
    last_error: Exception | None = None

    for engine in engines_to_try:
        try:
            LOGGER.info("Lendo planilha %s com engine=%s", path, engine or "auto")
            return pd.read_excel(path, sheet_name=None, engine=engine)
        except Exception as exc:
            last_error = exc
            LOGGER.warning("Falha ao ler %s com engine=%s: %s", path, engine, exc)

    raise RuntimeError(f"Não foi possível ler a planilha {path}") from last_error


def build_predictions_dataframe(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Consolida as abas dos participantes em uma única tabela de palpites."""

    participant_sheets = {
        sheet_name: sheet_df.copy()
        for sheet_name, sheet_df in sheets.items()
        if _is_participant_sheet(sheet_name, sheet_df)
    }
    if not participant_sheets:
        raise ValueError("Nenhuma aba de participante com as colunas esperadas foi encontrada.")

    raw_predictions = (
        pd.concat(participant_sheets, names=["Palpite"])
        .reset_index(level=0)
        .reset_index(drop=True)
    )

    predictions = normalize_match_dataframe(raw_predictions)
    predictions = predictions.loc[
        :,
        [
            "Palpite",
            "Data",
            "Mandante",
            "Placar Mandante",
            "Placar Visitante",
            "Visitante",
            "key",
            "Ganhador",
            "Palpite Valido",
        ],
    ].copy()

    missing_predictions = (~predictions["Palpite Valido"]).sum()
    if missing_predictions:
        LOGGER.warning("Foram encontrados %s palpites incompletos.", missing_predictions)

    return predictions.sort_values(["Palpite", "Data", "key"], kind="stable").reset_index(drop=True)


def build_schedule_dataframe(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Monta a grade de jogos a partir da aba `Resultado Real` ou da primeira aba válida."""

    if "Resultado Real" in sheets and REQUIRED_MATCH_COLUMNS.issubset(sheets["Resultado Real"].columns):
        schedule_source = sheets["Resultado Real"].copy()
    else:
        valid_sheets = [
            sheet_df.copy()
            for sheet_name, sheet_df in sheets.items()
            if _is_participant_sheet(sheet_name, sheet_df)
        ]
        if not valid_sheets:
            raise ValueError("Não foi possível localizar uma aba com a grade de jogos.")
        schedule_source = valid_sheets[0]

    schedule = normalize_match_dataframe(schedule_source)
    return (
        schedule.loc[:, ["Data", "Mandante", "Visitante", "key"]]
        .drop_duplicates(subset=["key"])
        .sort_values(["Data", "key"], kind="stable")
        .reset_index(drop=True)
    )


def normalize_match_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    """Normaliza datas, times, placares e chave técnica dos jogos."""

    missing_columns = REQUIRED_MATCH_COLUMNS.difference(frame.columns)
    if missing_columns:
        raise ValueError(f"Colunas obrigatórias ausentes: {sorted(missing_columns)}")

    normalized = frame.copy()
    normalized["Data"] = combine_date_time(normalized["Data"], normalized["Horário"])
    normalized["Mandante"] = _clean_text_series(normalized["Mandante"])
    normalized["Visitante"] = _clean_text_series(normalized["Visitante"])

    for score_column in SCORE_COLUMNS:
        normalized[score_column] = _normalize_score_series(normalized[score_column], score_column)

    normalized = normalized.loc[
        normalized["Data"].notna()
        & normalized["Mandante"].notna()
        & normalized["Visitante"].notna(),
        :,
    ].copy()

    normalized["key"] = build_game_keys(
        normalized["Data"],
        normalized["Mandante"],
        normalized["Visitante"],
    )
    normalized["Ganhador"] = classify_outcome(
        normalized["Placar Mandante"],
        normalized["Placar Visitante"],
    )
    normalized["Palpite Valido"] = normalized[list(SCORE_COLUMNS)].notna().all(axis=1)

    return normalized


def combine_date_time(date_values: pd.Series, time_values: pd.Series) -> pd.Series:
    """Combina colunas de data e horário em um `datetime64[ns]`."""

    date_part = pd.to_datetime(date_values, dayfirst=True, errors="coerce").dt.normalize()
    time_delta = _parse_time_to_timedelta(time_values)
    return date_part + time_delta


def build_game_keys(
    datetime_values: pd.Series,
    home_teams: pd.Series,
    away_teams: pd.Series,
) -> pd.Series:
    """Cria a chave técnica usada para cruzar planilha e JSON."""

    return (
        datetime_values.dt.strftime("%Y%m%d_%H%M")
        + "_"
        + _clean_text_series(home_teams)
        + "_"
        + _clean_text_series(away_teams)
    )


def classify_outcome(home_scores: pd.Series, away_scores: pd.Series) -> pd.Series:
    """Classifica o resultado como vitória do mandante, empate ou visitante."""

    home = pd.to_numeric(home_scores, errors="coerce")
    away = pd.to_numeric(away_scores, errors="coerce")
    conditions = [
        home.gt(away).fillna(False),
        home.eq(away).fillna(False),
        home.lt(away).fillna(False),
    ]
    outcomes = np.select(
        conditions,
        [OUTCOME_HOME, OUTCOME_DRAW, OUTCOME_AWAY],
        default=pd.NA,
    )
    return pd.Series(outcomes, index=home_scores.index, dtype="string")


def build_results_dataframe(
    results: ResultsMapping,
    schedule: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Transforma o JSON de resultados em tabela analítica, opcionalmente unida à grade."""

    result_records = [_parse_result_record(key, score) for key, score in results.items()]
    parsed_results = pd.DataFrame.from_records(result_records)

    if parsed_results.empty:
        parsed_results = pd.DataFrame(
            columns=["key", "Data", "Mandante", "Visitante", "Placar Mandante", "Placar Visitante"]
        )

    parsed_results["Data"] = pd.to_datetime(parsed_results["Data"], errors="coerce")
    for score_column in SCORE_COLUMNS:
        parsed_results[score_column] = _normalize_score_series(parsed_results[score_column], score_column)

    if schedule is not None and not schedule.empty:
        base_schedule = schedule.loc[:, ["key", "Data", "Mandante", "Visitante"]].drop_duplicates("key")
        merged_results = base_schedule.merge(
            parsed_results,
            on="key",
            how="outer",
            suffixes=("", "_json"),
            validate="1:1",
        )
        for column in ("Data", "Mandante", "Visitante"):
            json_column = f"{column}_json"
            if json_column in merged_results.columns:
                missing_base_values = merged_results[column].isna()
                merged_results.loc[missing_base_values, column] = merged_results.loc[
                    missing_base_values,
                    json_column,
                ]
                merged_results = merged_results.drop(columns=json_column)
    else:
        merged_results = parsed_results

    merged_results["Ganhador"] = classify_outcome(
        merged_results["Placar Mandante"],
        merged_results["Placar Visitante"],
    )
    merged_results["Jogo Realizado"] = merged_results[list(SCORE_COLUMNS)].notna().all(axis=1)
    merged_results["Status"] = np.select(
        [
            merged_results["Jogo Realizado"],
            merged_results[list(SCORE_COLUMNS)].notna().any(axis=1),
        ],
        ["Realizado", "Incompleto"],
        default="Pendente",
    )

    return (
        merged_results.loc[
            :,
            [
                "key",
                "Data",
                "Mandante",
                "Placar Mandante",
                "Placar Visitante",
                "Visitante",
                "Ganhador",
                "Jogo Realizado",
                "Status",
            ],
        ]
        .sort_values(["Data", "key"], kind="stable")
        .reset_index(drop=True)
    )


def score_predictions(predictions: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """Cruza palpites com resultados e calcula pontos por jogo."""

    completed_results = results.loc[
        results["Jogo Realizado"],
        ["key", "Placar Mandante", "Placar Visitante", "Ganhador"],
    ].rename(
        columns={
            "Placar Mandante": "Placar Mandante_realizado",
            "Placar Visitante": "Placar Visitante_realizado",
            "Ganhador": "Ganhador_realizado",
        }
    )

    scored = predictions.merge(
        completed_results,
        on="key",
        how="left",
        validate="m:1",
    )
    scored["Jogo Realizado"] = scored[
        ["Placar Mandante_realizado", "Placar Visitante_realizado"]
    ].notna().all(axis=1)

    has_valid_prediction = scored["Palpite Valido"]
    has_completed_result = scored["Jogo Realizado"]
    exact_score = (
        has_valid_prediction
        & has_completed_result
        & scored["Placar Mandante"].eq(scored["Placar Mandante_realizado"])
        & scored["Placar Visitante"].eq(scored["Placar Visitante_realizado"])
    )
    correct_outcome = (
        has_valid_prediction
        & has_completed_result
        & scored["Ganhador"].eq(scored["Ganhador_realizado"])
    )

    scored["Pontos"] = np.select(
        [exact_score, correct_outcome],
        [POINTS_EXACT_SCORE, POINTS_OUTCOME],
        default=0,
    ).astype("int64")
    scored["Acertou Placar"] = exact_score
    scored["Acertou Resultado"] = correct_outcome & ~exact_score

    scored = scored.sort_values(["Palpite", "Data", "key"], kind="stable").reset_index(drop=True)
    scored["PontosAcm"] = scored.groupby("Palpite", sort=False)["Pontos"].cumsum()

    return scored


def build_ranking(scored_predictions: pd.DataFrame) -> pd.DataFrame:
    """Gera ranking consolidado com critérios de desempate informativos."""

    ranking = (
        scored_predictions.groupby("Palpite", observed=True)
        .agg(
            Pontos=("Pontos", "sum"),
            **{
                "Acertos Placar": ("Acertou Placar", "sum"),
                "Acertos Resultado": ("Acertou Resultado", "sum"),
                "Jogos Pontuados": ("Pontos", lambda values: int((values > 0).sum())),
                "Jogos Realizados": ("Jogo Realizado", "sum"),
                "Palpites Inválidos": ("Palpite Valido", lambda values: int((~values).sum())),
            },
        )
        .reset_index()
    )

    ranking["Posição"] = (
        ranking["Pontos"]
        .rank(method="min", ascending=False)
        .astype("int64")
    )
    return (
        ranking.sort_values(
            ["Pontos", "Acertos Placar", "Acertos Resultado", "Palpite"],
            ascending=[False, False, False, True],
            kind="stable",
        )
        .loc[
            :,
            [
                "Posição",
                "Palpite",
                "Pontos",
                "Acertos Placar",
                "Acertos Resultado",
                "Jogos Pontuados",
                "Jogos Realizados",
                "Palpites Inválidos",
            ],
        ]
        .reset_index(drop=True)
    )


def build_points_by_datetime(scored_predictions: pd.DataFrame) -> pd.DataFrame:
    """Retorna pontos conquistados por participante em cada data/hora de jogo."""

    completed = scored_predictions.loc[scored_predictions["Jogo Realizado"], ["Palpite", "Data", "Pontos"]]
    if completed.empty:
        return pd.DataFrame()

    return (
        completed.groupby(["Palpite", "Data"], observed=True)["Pontos"]
        .sum()
        .unstack("Palpite", fill_value=0)
        .sort_index()
    )


def build_points_evolution(scored_predictions: pd.DataFrame) -> pd.DataFrame:
    """Retorna evolução acumulada dos pontos por data/hora."""

    points_by_datetime = build_points_by_datetime(scored_predictions)
    if points_by_datetime.empty:
        return points_by_datetime
    return points_by_datetime.cumsum().astype("int64")


def prepare_results_editor_dataframe(results: pd.DataFrame) -> pd.DataFrame:
    """Prepara a tabela de resultados para edição em Streamlit."""

    editor_df = results.loc[
        :,
        ["Data", "Mandante", "Placar Mandante", "Placar Visitante", "Visitante"],
    ].copy()
    editor_df["Horário"] = editor_df["Data"].dt.strftime("%H:%M")
    editor_df["Data"] = editor_df["Data"].dt.strftime("%d/%m/%Y")
    editor_df = editor_df.loc[
        :,
        ["Data", "Horário", "Mandante", "Placar Mandante", "Placar Visitante", "Visitante"],
    ]

    return editor_df


def results_editor_dataframe_to_mapping(editor_df: pd.DataFrame) -> ResultsMapping:
    """Valida uma tabela editada e converte para o formato do `resultados.json`."""

    required_columns = {"Data", "Horário", "Mandante", "Visitante", *SCORE_COLUMNS}
    missing_columns = required_columns.difference(editor_df.columns)
    if missing_columns:
        raise ValueError(f"Colunas ausentes na tabela editada: {sorted(missing_columns)}")

    clean_editor = editor_df.copy()
    clean_editor = clean_editor.dropna(how="all")
    clean_editor = clean_editor.loc[
        clean_editor[["Data", "Horário", "Mandante", "Visitante"]].notna().any(axis=1),
        :,
    ].copy()

    if clean_editor.empty:
        return {}

    normalized = normalize_match_dataframe(clean_editor)
    if len(normalized) != len(clean_editor):
        raise ValueError("Existem linhas com data, horário, mandante ou visitante inválidos.")

    partial_scores = normalized[list(SCORE_COLUMNS)].notna().sum(axis=1).eq(1)
    if partial_scores.any():
        invalid_games = normalized.loc[partial_scores, ["Data", "Mandante", "Visitante"]]
        raise ValueError(
            "Há jogos com placar parcial. Preencha os dois placares ou deixe ambos em branco: "
            f"{invalid_games.to_dict(orient='records')}"
        )

    duplicated_keys = normalized.loc[normalized["key"].duplicated(), "key"].unique()
    if len(duplicated_keys):
        raise ValueError(f"Existem jogos duplicados na edição: {list(duplicated_keys)}")

    results: ResultsMapping = {}
    for record in normalized.loc[:, ["key", *SCORE_COLUMNS]].to_dict(orient="records"):
        results[str(record["key"])] = {
            "Mandante": _score_to_json_value(record["Placar Mandante"]),
            "Visitante": _score_to_json_value(record["Placar Visitante"]),
        }

    return results


def save_results_from_editor(
    editor_df: pd.DataFrame,
    results_path: Path | str = DEFAULT_RESULTS_PATH,
) -> ResultsMapping:
    """Valida e salva os resultados editados no JSON."""

    results = results_editor_dataframe_to_mapping(editor_df)
    write_results_json(results, results_path)
    return results


class Palpites:
    """Interface compatível para carregar palpites, ranking e evolução do bolão."""

    def __init__(
        self,
        excel_path: Path | str = DEFAULT_EXCEL_PATH,
        results_path: Path | str = DEFAULT_RESULTS_PATH,
        excel_engine: str | None = DEFAULT_EXCEL_ENGINE,
    ) -> None:
        self.config = BolaoConfig(
            excel_path=Path(excel_path),
            results_path=Path(results_path),
            excel_engine=excel_engine,
        )
        self.palpites_com_placar: pd.DataFrame | None = None
        self.ranking: pd.DataFrame | None = None
        self.evolucao: pd.DataFrame | None = None
        self.resultados: pd.DataFrame | None = None

    def get_palpites(self) -> pd.DataFrame:
        """Retorna todos os palpites com placar realizado e pontuação."""

        self._ensure_loaded()
        return self.palpites_com_placar.copy()  # type: ignore[union-attr]

    def get_palpites_dia(self, acumulado: bool = False) -> pd.DataFrame:
        """Retorna os pontos por data/hora, acumulados ou não."""

        self._ensure_loaded()
        if acumulado:
            return self.evolucao.copy()  # type: ignore[union-attr]
        return build_points_by_datetime(self.palpites_com_placar)  # type: ignore[arg-type]

    def get_points(self) -> pd.DataFrame:
        """Retorna ranking simples, preservando a saída anterior com índice por participante."""

        self._ensure_loaded()
        return (
            self.ranking.set_index("Palpite")[["Pontos"]]  # type: ignore[union-attr]
            .sort_values("Pontos", ascending=False)
            .copy()
        )

    def get_ranking(self) -> pd.DataFrame:
        """Retorna ranking detalhado."""

        self._ensure_loaded()
        return self.ranking.copy()  # type: ignore[union-attr]

    def get_resultados(self) -> pd.DataFrame:
        """Retorna a grade de jogos com os resultados carregados do JSON."""

        self._ensure_loaded()
        return self.resultados.copy()  # type: ignore[union-attr]

    def _ensure_loaded(self) -> None:
        if self.palpites_com_placar is not None:
            return

        data = load_bolao_data(self.config)
        self.palpites_com_placar = data.palpites
        self.ranking = data.ranking
        self.evolucao = data.evolucao
        self.resultados = data.resultados


def _build_excel_engine_priority(excel_engine: str | None) -> list[str | None]:
    engines: list[str | None] = []
    for engine in (excel_engine, DEFAULT_EXCEL_ENGINE, "openpyxl", None):
        if engine not in engines:
            engines.append(engine)
    return engines


def _is_participant_sheet(sheet_name: str, sheet_df: pd.DataFrame) -> bool:
    return sheet_name not in EXCLUDED_SHEETS and REQUIRED_MATCH_COLUMNS.issubset(sheet_df.columns)


def _clean_text_series(values: pd.Series) -> pd.Series:
    return values.astype("string").str.strip().replace({"": pd.NA})


def _normalize_score_series(values: pd.Series, column_name: str) -> pd.Series:
    numeric_values = pd.to_numeric(values, errors="coerce")
    invalid_fractional = numeric_values.notna() & numeric_values.mod(1).ne(0)
    if invalid_fractional.any():
        raise ValueError(f"A coluna {column_name!r} contém placares não inteiros.")
    if numeric_values.lt(0).fillna(False).any():
        raise ValueError(f"A coluna {column_name!r} contém placares negativos.")
    return numeric_values.astype("Int64")


def _normalize_score_value(value: Any, game_key: str) -> ScoreValue:
    if value is None or pd.isna(value) or value == "":
        return None

    try:
        score = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Placar inválido no jogo {game_key!r}: {value!r}") from exc

    if score < 0:
        raise ValueError(f"Placar negativo no jogo {game_key!r}: {value!r}")
    return score


def _score_to_json_value(value: Any) -> ScoreValue:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _parse_time_to_timedelta(time_values: pd.Series) -> pd.Series:
    time_text = time_values.astype("string").str.strip()

    time_parts = time_text.str.extract(
        r"(?:(?:\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\s+)?"
        r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?$"
    )
    hour = pd.to_numeric(time_parts["hour"], errors="coerce")
    minute = pd.to_numeric(time_parts["minute"], errors="coerce")
    second = pd.to_numeric(time_parts["second"], errors="coerce").fillna(0)
    valid_time_text = (
        hour.between(0, 23, inclusive="both")
        & minute.between(0, 59, inclusive="both")
        & second.between(0, 59, inclusive="both")
    )
    text_delta = (
        pd.to_timedelta(hour.fillna(0), unit="h")
        + pd.to_timedelta(minute.fillna(0), unit="m")
        + pd.to_timedelta(second.fillna(0), unit="s")
    )
    parsed_delta = text_delta.where(valid_time_text)

    numeric_time = pd.to_numeric(time_values, errors="coerce")
    numeric_delta = pd.to_timedelta(numeric_time, unit="D")
    valid_numeric_time = numeric_time.between(0, 1, inclusive="left")
    parsed_delta = parsed_delta.fillna(numeric_delta.where(valid_numeric_time))

    return parsed_delta


def _parse_result_record(game_key: str, score_payload: dict[str, ScoreValue]) -> dict[str, Any]:
    parsed_key = _parse_game_key(game_key)
    return {
        "key": game_key,
        "Data": parsed_key["Data"],
        "Mandante": parsed_key["Mandante"],
        "Visitante": parsed_key["Visitante"],
        "Placar Mandante": score_payload.get("Mandante"),
        "Placar Visitante": score_payload.get("Visitante"),
    }


def _parse_game_key(game_key: str) -> dict[str, Any]:
    try:
        date_text, time_text, home_team, away_team = game_key.split("_", 3)
    except ValueError as exc:
        raise ValueError(f"Chave de jogo fora do padrão esperado: {game_key!r}") from exc

    match_datetime = pd.to_datetime(
        f"{date_text} {time_text}",
        format="%Y%m%d %H%M",
        errors="coerce",
    )
    if pd.isna(match_datetime):
        raise ValueError(f"Data/hora inválida na chave do jogo: {game_key!r}")

    return {
        "Data": match_datetime,
        "Mandante": home_team.strip(),
        "Visitante": away_team.strip(),
    }


def main() -> None:
    """Executa um resumo rápido do ranking no terminal."""

    configure_logging()
    bolao = Palpites()
    ranking = bolao.get_ranking()
    print(ranking.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
