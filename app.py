from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from palpites import (
    DEFAULT_EXCEL_PATH,
    DEFAULT_RESULTS_PATH,
    BolaoConfig,
    load_bolao_data,
    prepare_results_editor_dataframe,
    save_results_from_editor,
)

st.set_page_config(
    page_title="Placar do Bolão Copa 2026",
    page_icon="🏆",
    layout="wide",
)


def main() -> None:
    st.title("🏆 Placar do Bolão Copa 2026")
    st.caption(
        "Ranking, palpites individuais, evolução de pontos e atualização de resultados."
    )

    excel_path, results_path = render_sidebar()

    try:
        data = load_dashboard_data(
            str(excel_path),
            str(results_path),
            get_file_signature(excel_path),
            get_file_signature(results_path),
        )
    except Exception as exc:
        st.error(f"Não foi possível carregar os dados: {exc}")
        st.stop()

    render_summary_metrics(data.ranking, data.resultados)

    (
        ranking_tab,
        individual_tab,
        game_summary_tab,
        evolution_tab,
        results_tab,
        editor_tab,
    ) = st.tabs(
        [
            "Ranking",
            "Palpite individual",
            "Resumo por jogo",
            "Evolução",
            "Resultados",
            "Atualizar resultados",
        ]
    )

    with ranking_tab:
        render_ranking_tab(data.ranking, data.resultados)

    with individual_tab:
        render_individual_tab(data.palpites, data.ranking)

    with game_summary_tab:
        render_game_summary_tab(data.palpites, data.resultados, data.ranking)

    with evolution_tab:
        render_evolution_tab(data.evolucao, data.ranking)

    with results_tab:
        render_results_tab(data.resultados)

    with editor_tab:
        render_results_editor_tab(data.resultados, results_path)


def render_sidebar() -> tuple[Path, Path]:
    # st.sidebar.header("Arquivos")
    # excel_path = Path(
    #     st.sidebar.text_input("Planilha de palpites", value=str(DEFAULT_EXCEL_PATH))
    # )
    # results_path = Path(
    #     st.sidebar.text_input("JSON de resultados", value=str(DEFAULT_RESULTS_PATH))
    # )

    # st.sidebar.divider()
    # st.sidebar.markdown(
    #     "**Pontuação:** 3 pontos para placar exato e 1 ponto para vencedor/empate correto."
    # )

    # if st.sidebar.button("Recarregar dados", width='stretch'):
    #     st.cache_data.clear()
    #     st.rerun()

    return DEFAULT_EXCEL_PATH, DEFAULT_RESULTS_PATH


def get_file_signature(path: Path) -> tuple[int, int]:
    file_stat = path.stat()
    return file_stat.st_mtime_ns, file_stat.st_size


@st.cache_data(show_spinner="Carregando planilha, resultados e pontuação...")
def load_dashboard_data(
    excel_path: str,
    results_path: str,
    excel_signature: tuple[int, int],
    results_signature: tuple[int, int],
):
    _ = excel_signature, results_signature
    return load_bolao_data(
        BolaoConfig(
            excel_path=Path(excel_path),
            results_path=Path(results_path),
        )
    )


def render_summary_metrics(
    ranking: pd.DataFrame, results: pd.DataFrame
) -> None:
    completed_games = f"{int(results['Jogo Realizado'].sum())}/72"
    pending_games = int((results["Status"] == "Pendente").sum())
    leader_points = int(ranking["Pontos"].max()) if not ranking.empty else 0
    last_completed = results.loc[results["Jogo Realizado"], "Data"].max()
    last_completed_label = (
        last_completed.strftime("%d/%m/%Y %H:%M")
        if pd.notna(last_completed)
        else "Sem jogos realizados"
    )

    col_participants, col_completed, col_pending, col_leader, col_last = (
        st.columns(5)
    )
    col_participants.metric(
        "Participantes", f"{ranking['Palpite'].nunique():,}".replace(",", ".")
    )
    col_completed.metric("Jogos realizados", completed_games)
    col_pending.metric("Jogos pendentes", pending_games)
    col_leader.metric("Pontos do líder", leader_points)
    col_last.metric("Último jogo pontuado", last_completed_label)


def render_ranking_tab(ranking: pd.DataFrame, results: pd.DataFrame) -> None:
    st.subheader("Ranking de pontos por palpitador")
    st.dataframe(
        ranking,
        hide_index=True,
        width="content",
        column_config={
            "Posição": st.column_config.NumberColumn(
                alignment="center", format="%dº"
            ),
            "Pontos": st.column_config.NumberColumn(alignment="center"),
            "Acertos Placar": st.column_config.NumberColumn(alignment="center"),
            "Acertos Resultado": st.column_config.NumberColumn(
                alignment="center"
            ),
            "Jogos Pontuados": st.column_config.NumberColumn(
                alignment="center"
            ),
            "Jogos Realizados": st.column_config.NumberColumn(
                alignment="center"
            ),
        },
    )
    render_shareable_ranking(ranking, results)


def render_individual_tab(
    scored_predictions: pd.DataFrame, ranking: pd.DataFrame
) -> None:
    st.subheader("Consulta de palpite individual")

    participants = ranking["Palpite"].tolist()
    selected_participant = st.selectbox("Palpitador", participants)

    participant_predictions = scored_predictions.loc[
        scored_predictions["Palpite"] == selected_participant,
        :,
    ].copy()

    status_filter = st.radio(
        "Filtro",
        ["Todos", "Jogos realizados", "Jogos pontuados"],
        horizontal=True,
    )
    if status_filter == "Jogos realizados":
        participant_predictions = participant_predictions.loc[
            participant_predictions["Jogo Realizado"], :
        ]
    elif status_filter == "Jogos pontuados":
        participant_predictions = participant_predictions.loc[
            participant_predictions["Pontos"] > 0, :
        ]

    st.dataframe(
        format_prediction_table(participant_predictions),
        hide_index=True,
        width="content",
        column_config={
            "Data/Hora": st.column_config.DatetimeColumn(
                alignment="center", format="DD/MM/YYYY HH:mm"
            ),
            "Palpite": st.column_config.TextColumn(alignment="center"),
            "Resultado Real": st.column_config.TextColumn(alignment="center"),
            "Situação": st.column_config.TextColumn(alignment="center"),
            "Resultado Palpite": st.column_config.TextColumn(
                alignment="center"
            ),
            "Resultado Oficial": st.column_config.TextColumn(
                alignment="center"
            ),
            "Pontos": st.column_config.NumberColumn(alignment="center"),
            "Pontos Acumulados": st.column_config.NumberColumn(
                alignment="center"
            ),
        },
    )
    st.caption(
        "Legenda: ✅ placar cravado | 🟡 resultado correto | ❌ erro | "
        "⏳ aguardando resultado"
    )


def render_shareable_ranking(
    ranking: pd.DataFrame, results: pd.DataFrame
) -> None:
    st.divider()
    st.subheader("Ranking para compartilhar")
    st.caption(
        "Imagem pronta para baixar e enviar no grupo, com todos os palpitadores."
    )

    completed_games = int(results["Jogo Realizado"].sum())
    total_games = len(results)
    ranking_image = create_ranking_image(
        ranking,
        completed_games=completed_games,
        total_games=total_games,
    )
    generated_at = datetime.now().strftime("%Y%m%d_%H%M")

    st.image(
        ranking_image, caption="Prévia do ranking completo", width="stretch"
    )
    st.download_button(
        "Baixar ranking em PNG",
        data=ranking_image,
        file_name=f"ranking_bolao_{generated_at}.png",
        mime="image/png",
        type="primary",
        width="stretch",
    )

    ranking_text = format_ranking_text(
        ranking,
        completed_games=completed_games,
        total_games=total_games,
    )
    with st.expander("Ranking em texto para copiar"):
        st.code(ranking_text)
        st.download_button(
            "Baixar ranking em TXT",
            data=ranking_text.encode("utf-8"),
            file_name=f"ranking_bolao_{generated_at}.txt",
            mime="text/plain",
            width="stretch",
        )


def render_evolution_tab(
    evolution: pd.DataFrame, ranking: pd.DataFrame
) -> None:
    st.subheader("Evolução dos pontos acumulados por dia e hora")

    if evolution.empty:
        st.info("Ainda não há jogos realizados para montar a evolução.")
        return

    ordered_participants = ranking["Palpite"].tolist()
    default_participants = ordered_participants[:10]
    selected_participants = st.multiselect(
        "Participantes no gráfico",
        ordered_participants,
        default=default_participants,
    )

    if not selected_participants:
        st.warning("Selecione ao menos um participante.")
        return

    filtered_evolution = evolution.loc[:, selected_participants]
    st.line_chart(filtered_evolution, width="stretch", height=800)

    with st.expander("Ver tabela de evolução"):
        st.dataframe(
            filtered_evolution.reset_index().rename(
                columns={"Data": "Data/Hora"}
            ),
            hide_index=True,
            width="content",
            column_config={
                "Data/Hora": st.column_config.DatetimeColumn(
                    alignment="center", format="DD/MM/YYYY HH:mm"
                )
            },
        )


def render_results_tab(results: pd.DataFrame) -> None:
    st.subheader("Resultados dos jogos")

    status_options = [
        "Todos",
        *sorted(results["Status"].dropna().unique().tolist()),
    ]
    selected_status = st.selectbox("Status", status_options)

    filtered_results = results.copy()
    if selected_status != "Todos":
        filtered_results = filtered_results.loc[
            filtered_results["Status"] == selected_status, :
        ]

    st.dataframe(
        format_results_table(filtered_results),
        hide_index=True,
        width="content",
        column_config={
            "Data/Hora": st.column_config.DatetimeColumn(
                alignment="center", format="DD/MM/YYYY HH:mm"
            ),
            "Resultado": st.column_config.TextColumn(alignment="center"),
            "Vencedor": st.column_config.TextColumn(alignment="center"),
            "Status": st.column_config.TextColumn(alignment="center"),
        },
    )


def render_game_summary_tab(
    palpites: pd.DataFrame, results: pd.DataFrame, ranking: pd.DataFrame
) -> None:
    st.subheader("Resumo de palpites por jogo")
    st.caption(
        "Veja o próximo jogo pendente por padrão e filtre todos os palpites por jogo selecionado."
    )

    if results.empty:
        st.info("Ainda não há jogos cadastrados.")
        return

    game_labels = {
        row["key"]: (
            f"{row['Data'].strftime('%d/%m %H:%M')} — {row['Mandante']} x {row['Visitante']} "
            f"({row['Status']})"
        )
        for _, row in results.iterrows()
    }

    game_keys = list(results["key"])
    pending_keys = results.loc[results["Status"] == "Pendente", "key"].tolist()
    default_key = pending_keys[0] if pending_keys else game_keys[0]
    default_index = game_keys.index(default_key)

    selected_game_key = st.selectbox(
        "Selecione o jogo",
        options=game_keys,
        format_func=lambda key: game_labels[key],
        index=default_index,
    )

    selected_game = results.loc[results["key"] == selected_game_key].iloc[0]
    home_team = selected_game["Mandante"]
    away_team = selected_game["Visitante"]
    result_score = (
        format_score_pair(
            pd.Series([selected_game["Placar Mandante"]]),
            pd.Series([selected_game["Placar Visitante"]]),
        ).iat[0]
        if selected_game["Jogo Realizado"]
        else "—"
    )

    col_game, col_datetime, col_status, col_result = st.columns(4)
    col_game.metric("Jogo", f"{home_team} x {away_team}")
    col_datetime.metric(
        "Data/Hora", selected_game["Data"].strftime("%d/%m %H:%M")
    )
    col_status.metric("Status", selected_game["Status"])
    col_result.metric("Resultado oficial", result_score)

    st.markdown("### Distribuição de palpites")
    summary_table = build_game_summary_table(
        palpites, selected_game_key, home_team, away_team
    )
    if summary_table.empty:
        st.info("Ainda não há palpites registrados para este jogo.")
    else:
        st.dataframe(
            summary_table,
            hide_index=True,
            width="content",
            column_config={
                home_team: st.column_config.NumberColumn(alignment="center"),
                away_team: st.column_config.NumberColumn(alignment="center"),
                "Qtd palpites": st.column_config.NumberColumn(
                    alignment="center"
                ),
                "Ganhador": st.column_config.TextColumn(alignment="center"),
            },
        )

    st.markdown("### Palpites individuais")
    with st.expander("Ver todos os palpites por palpitador para este jogo"):
        player_table = format_game_predictions_table(
            palpites.loc[palpites["key"] == selected_game_key, :].copy(),
            ranking,
        )
        if player_table.empty:
            st.info("Nenhum palpite encontrado para este jogo.")
        else:
            st.dataframe(
                player_table,
                hide_index=True,
                width="content",
                column_config={
                    "Posição": st.column_config.NumberColumn(
                        alignment="center", format="%dº"
                    ),
                    "Palpite": st.column_config.TextColumn(alignment="center"),
                    "Placar": st.column_config.TextColumn(alignment="center"),
                    "Resultado Real": st.column_config.TextColumn(
                        alignment="center"
                    ),
                    "Situação": st.column_config.TextColumn(alignment="center"),
                    "Pontos": st.column_config.NumberColumn(alignment="center"),
                    "Pontos Acumulados": st.column_config.NumberColumn(
                        alignment="center"
                    ),
                },
            )

    st.markdown("### Imagens para compartilhar")
    if not summary_table.empty:
        distribution_image = create_game_distribution_image(
            summary_table, home_team, away_team, selected_game
        )
        st.image(
            distribution_image,
            caption="Distribuição de palpites",
            width="stretch",
        )
        st.download_button(
            "Baixar distribuição em PNG",
            data=distribution_image,
            file_name=f"distribuicao_palpite_{selected_game_key}.png",
            mime="image/png",
            width="stretch",
        )

    if not player_table.empty:
        predictions_image = create_game_predictions_image(
            player_table, selected_game
        )
        st.image(
            predictions_image, caption="Palpites individuais", width="stretch"
        )
        st.download_button(
            "Baixar palpites individuais em PNG",
            data=predictions_image,
            file_name=f"palpites_individuais_{selected_game_key}.png",
            mime="image/png",
            width="stretch",
        )


def build_game_summary_table(
    palpites: pd.DataFrame,
    game_key: str,
    home_team: str,
    away_team: str,
) -> pd.DataFrame:
    game_predictions = palpites.loc[palpites["key"] == game_key].copy()
    if game_predictions.empty:
        return pd.DataFrame(
            columns=["Ganhador", home_team, away_team, "Qtd palpites"]
        )

    summary = (
        game_predictions.groupby(
            ["Ganhador", "Placar Mandante", "Placar Visitante"], observed=True
        )
        .size()
        .reset_index(name="Qtd palpites")
        .sort_values(
            ["Qtd palpites", "Ganhador", "Placar Mandante", "Placar Visitante"],
            ascending=[False, True, True, True],
        )
    )
    summary["Ganhador"] = summary["Ganhador"].fillna("—")
    return summary.rename(
        columns={
            "Placar Mandante": home_team,
            "Placar Visitante": away_team,
        }
    )


def format_game_predictions_table(
    game_predictions: pd.DataFrame, ranking: pd.DataFrame | None = None
) -> pd.DataFrame:
    if game_predictions.empty:
        return pd.DataFrame(
            columns=[
                "Posição",
                "Palpite",
                "Placar",
                "Resultado Real",
                "Situação",
                "Pontos",
                "Pontos Acumulados",
            ]
        )

    formatted = game_predictions.copy()
    # adicionar posição quando ranking disponível
    if ranking is not None and not ranking.empty:
        pos = ranking.loc[:, ["Palpite", "Posição"]].copy()
        formatted = formatted.merge(
            pos, on="Palpite", how="left", validate="m:1"
        )
    else:
        formatted["Posição"] = pd.NA
    formatted["Placar"] = format_score_pair(
        formatted["Placar Mandante"],
        formatted["Placar Visitante"],
    )
    formatted["Resultado Real"] = format_score_pair(
        formatted["Placar Mandante_realizado"],
        formatted["Placar Visitante_realizado"],
    )
    formatted["Situação"] = build_prediction_status(formatted)

    return (
        formatted.loc[
            :,
            [
                "Posição",
                "Palpite",
                "Placar",
                "Resultado Real",
                "Situação",
                "Pontos",
                "PontosAcm",
            ],
        ]
        .rename(columns={"PontosAcm": "Pontos Acumulados"})
        .sort_values(
            ["Posição", "Pontos", "Palpite"],
            ascending=[True, False, True],
            kind="stable",
        )
        .reset_index(drop=True)
    )


def render_results_editor_tab(
    results: pd.DataFrame, results_path: Path
) -> None:
    st.subheader("Modificar ou incluir resultados")
    st.info(
        "Novos jogos só impactam a pontuação se também existirem nas abas de palpites da planilha "
        "com a mesma data, horário, mandante e visitante."
    )

    editor_df = prepare_results_editor_dataframe(results)
    with st.form("results_editor_form"):
        edited_results = st.data_editor(
            editor_df,
            hide_index=True,
            num_rows="dynamic",
            width="content",
            column_config={
                "Data": st.column_config.TextColumn(
                    "Data", help="Formato: dd/mm/aaaa", alignment="center"
                ),
                "Horário": st.column_config.TextColumn(
                    "Horário", help="Formato: HH:MM", alignment="center"
                ),
                "Mandante": st.column_config.TextColumn("Mandante"),
                "Visitante": st.column_config.TextColumn("Visitante"),
                "Placar Mandante": st.column_config.NumberColumn(
                    "Placar Mandante",
                    min_value=0,
                    step=1,
                    format="%d",
                    alignment="center",
                ),
                "Placar Visitante": st.column_config.NumberColumn(
                    "Placar Visitante",
                    min_value=0,
                    step=1,
                    format="%d",
                    alignment="center",
                ),
            },
        )
        submitted = st.form_submit_button(
            "Salvar resultados e recalcular", type="primary"
        )

    if not submitted:
        return

    try:
        save_results_from_editor(edited_results, results_path)
    except Exception as exc:
        st.error(f"Não foi possível salvar os resultados: {exc}")
        return

    st.cache_data.clear()
    st.success(
        f"Resultados salvos em `{results_path}`. Recalculando pontuação..."
    )
    st.rerun()


def format_prediction_table(scored_predictions: pd.DataFrame) -> pd.DataFrame:
    formatted = scored_predictions.copy()
    formatted["Data/Hora"] = formatted["Data"].dt.strftime("%d/%m/%Y %H:%M")
    formatted["Situação"] = build_prediction_status(formatted)
    formatted["Palpite"] = format_score_pair(
        formatted["Placar Mandante"],
        formatted["Placar Visitante"],
    )
    formatted["Resultado Real"] = format_score_pair(
        formatted["Placar Mandante_realizado"],
        formatted["Placar Visitante_realizado"],
    )

    return formatted.loc[
        :,
        [
            "Data/Hora",
            "Mandante",
            "Palpite",
            "Visitante",
            "Resultado Real",
            "Situação",
            "Ganhador",
            "Ganhador_realizado",
            "Pontos",
            "PontosAcm",
        ],
    ].rename(
        columns={
            "Ganhador": "Resultado Palpite",
            "Ganhador_realizado": "Resultado Oficial",
            "PontosAcm": "Pontos Acumulados",
        }
    )


def build_prediction_status(scored_predictions: pd.DataFrame) -> pd.Series:
    # Garantir colunas necessárias; tentar inferir se ausentes
    df = scored_predictions
    status = pd.Series("⏳", index=df.index, dtype="string")

    # Inferir se o jogo foi realizado
    if "Jogo Realizado" in df.columns:
        completed_game = df["Jogo Realizado"].fillna(False)
    else:
        completed_game = df.get("Placar Mandante_realizado")
        completed_game = (
            completed_game.notna()
            if completed_game is not None
            else pd.Series(False, index=df.index)
        )

    # Inferir acertos a partir das colunas existentes
    if "Acertou Placar" in df.columns:
        exact_score = df["Acertou Placar"].fillna(False)
    else:
        exact_score = df.get("Placar Mandante").eq(
            df.get("Placar Mandante_realizado")
        ) & df.get("Placar Visitante").eq(df.get("Placar Visitante_realizado"))
        exact_score = (
            exact_score.fillna(False)
            if hasattr(exact_score, "fillna")
            else pd.Series(False, index=df.index)
        )

    if "Acertou Resultado" in df.columns:
        correct_outcome = df["Acertou Resultado"].fillna(False)
    else:
        correct_outcome = df.get("Ganhador").eq(df.get("Ganhador_realizado"))
        correct_outcome = (
            correct_outcome.fillna(False)
            if hasattr(correct_outcome, "fillna")
            else pd.Series(False, index=df.index)
        )

    # Prioridade: placar exato > resultado correto > erro
    status.loc[completed_game] = "❌"
    status.loc[completed_game & correct_outcome] = "🟡"
    status.loc[completed_game & exact_score] = "✅"

    return status


def format_results_table(results: pd.DataFrame) -> pd.DataFrame:
    formatted = results.copy()
    formatted["Data/Hora"] = formatted["Data"].dt.strftime("%d/%m/%Y %H:%M")
    formatted["Resultado"] = format_score_pair(
        formatted["Placar Mandante"],
        formatted["Placar Visitante"],
    )

    return formatted.loc[
        :,
        [
            "Data/Hora",
            "Mandante",
            "Resultado",
            "Visitante",
            "Ganhador",
            "Status",
        ],
    ].rename(columns={"Ganhador": "Vencedor"})


def format_score_pair(
    home_scores: pd.Series, away_scores: pd.Series
) -> pd.Series:
    home = home_scores.astype("Int64").astype("string").fillna("—")
    away = away_scores.astype("Int64").astype("string").fillna("—")
    return home + " x " + away


def create_ranking_image(
    ranking: pd.DataFrame,
    completed_games: int,
    total_games: int,
) -> bytes:
    from PIL import Image, ImageDraw

    ranking_to_share = ranking.loc[
        :,
        [
            "Posição",
            "Palpite",
            "Pontos",
            "Acertos Placar",
            "Acertos Resultado",
        ],
    ].copy()

    width = 1800
    margin = 80
    title_height = 200
    header_height = 76
    row_height = 70
    footer_height = 92
    height = (
        margin
        + title_height
        + header_height
        + row_height * len(ranking_to_share)
        + footer_height
        + margin
    )

    image = Image.new("RGB", (width, height), "#F8FAFC")
    draw = ImageDraw.Draw(image)

    title_font = load_image_font(size=70, bold=True)
    subtitle_font = load_image_font(size=40)
    games_counter_font = load_image_font(size=60, bold=True)
    header_font = load_image_font(size=50, bold=True)
    row_font = load_image_font(size=50)
    footer_font = load_image_font(size=35)

    columns = [
        ("Pos.", "Posição", 130),
        ("Palpitador", "Palpite", 750),
        ("Pts", "Pontos", 140),
        ("Placar", "Acertos Placar", 250),
        ("Resultado", "Acertos Resultado", 360),
    ]
    table_width = sum(column_width for _, _, column_width in columns)
    table_left = (width - table_width) // 2
    table_right = table_left + table_width

    draw.rounded_rectangle(
        (table_left, margin, table_right, margin + title_height - 22),
        radius=34,
        fill="#0F172A",
    )
    draw.text(
        (table_left + 50, margin + 34),
        "Ranking Bolão Copa 2026",
        font=title_font,
        fill="#FFFFFF",
    )
    draw.text(
        (table_left + 54, margin + 125),
        f"Atualizado em {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        font=subtitle_font,
        fill="#CBD5E1",
    )
    games_counter = f"Jogos: {completed_games}/{total_games}"
    games_counter_width = draw.textlength(
        games_counter, font=games_counter_font
    )
    draw.text(
        (table_right - 54 - games_counter_width, margin + 104),
        games_counter,
        font=games_counter_font,
        fill="#CBD5E1",
    )

    current_y = margin + title_height
    current_x = table_left
    draw.rectangle(
        (table_left, current_y, table_right, current_y + header_height),
        fill="#1E293B",
    )
    for label, _, column_width in columns:
        draw.text(
            (current_x + 12, current_y + 10),
            label,
            font=header_font,
            fill="#FFFFFF",
        )
        current_x += column_width

    current_y += header_height
    for row_number, row in enumerate(
        ranking_to_share.to_dict(orient="records")
    ):
        row_fill = "#FFFFFF" if row_number % 2 == 0 else "#F1F5F9"
        if int(row["Posição"]) == 1:
            row_fill = "#FEF3C7"
        elif int(row["Posição"]) == 2:
            row_fill = "#E2E8F0"
        elif int(row["Posição"]) == 3:
            row_fill = "#FED7AA"

        draw.rectangle(
            (table_left, current_y, table_right, current_y + row_height),
            fill=row_fill,
        )

        current_x = table_left
        for _, field_name, column_width in columns:
            value = str(row[field_name])
            if field_name == "Posição":
                emoji_position = {
                    '1': '🥇',
                    '2': '🥈',
                    '3': '🥉',
                }
                value = emoji_position.get(value, f"{value:>2}º")
            if field_name == "Pontos":
                value = f"{value:>2}"
            if field_name == "Acertos Placar":
                value = f"{value:>5}"
            if field_name == "Acertos Resultado":
                value = f"{value:>9}"
            value = truncate_text(draw, value, row_font, column_width - 18)
            draw.text(
                (current_x + 12, current_y + 11),
                value,
                font=row_font,
                fill="#0F172A",
                embedded_color=True
            )
            current_x += column_width

        current_y += row_height

    draw.rectangle(
        (table_left, current_y, table_right, current_y + 1), fill="#CBD5E1"
    )
    draw.text(
        (table_left, current_y + 18),
        "Critério: 3 pontos para placar exato; 1 ponto para vencedor/empate correto.",
        font=footer_font,
        fill="#475569",
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def load_image_font(size: int, bold: bool = False):
    from PIL import ImageFont

    font_candidates = [
        Path(
            "C:/Windows/Fonts/seguiemj.ttf"
            if bold
            else "C:/Windows/Fonts/seguiemj.ttf"
        ),
        Path(
            "C:/Windows/Fonts/arialbd.ttf"
            if bold
            else "C:/Windows/Fonts/arial.ttf"
        ),
        Path(
            "C:/Windows/Fonts/seguisb.ttf"
            if bold
            else "C:/Windows/Fonts/segoeui.ttf"
        ),
    ]
    for font_path in font_candidates:
        if not font_path.exists():
            continue
        try:
            return ImageFont.truetype(str(font_path), size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def truncate_text(draw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text

    suffix = "..."
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1]
    return text + suffix


def create_game_distribution_image(
    summary: pd.DataFrame,
    home_team: str,
    away_team: str,
    selected_game: pd.Series,
) -> bytes:
    from PIL import Image, ImageDraw

    width = 800
    margin = 40
    title_height = 120
    header_height = 56
    row_height = 46
    footer_height = 64
    height = (
        margin
        + title_height
        + header_height
        + row_height * max(1, len(summary))
        + footer_height
        + margin
    )

    image = Image.new("RGB", (width, height), "#F8FAFC")
    draw = ImageDraw.Draw(image)

    title_font = load_image_font(size=40, bold=True)
    subtitle_font = load_image_font(size=20)
    header_font = load_image_font(size=22, bold=True)
    row_font = load_image_font(size=20)
    footer_font = load_image_font(size=18)

    draw.rounded_rectangle(
        (margin, margin, width - margin, margin + title_height - 10),
        radius=16,
        fill="#0F172A",
    )
    draw.text(
        (margin + 16, margin + 12),
        "Distribuição de palpites",
        font=title_font,
        fill="#FFFFFF",
    )
    draw.text(
        (margin + 16, margin + 60),
        f"{selected_game['Mandante']} x {selected_game['Visitante']} — {selected_game['Data'].strftime('%d/%m %H:%M')}",
        font=subtitle_font,
        fill="#CBD5E1",
    )

    current_y = margin + title_height
    current_x = margin
    column_defs = [
        ("Resultado", 220),
        (home_team, 170),
        (away_team, 170),
        ("Qtd palpites", 120),
    ]

    draw.rectangle(
        (margin, current_y, width - margin, current_y + header_height),
        fill="#1E293B",
    )
    for label, col_width in column_defs:
        draw.text(
            (current_x + 8, current_y + 12),
            label,
            font=header_font,
            fill="#FFFFFF",
        )
        current_x += col_width

    current_y += header_height
    for k, row in enumerate(summary.to_dict(orient="records")):
        row_fill = (
            "#FFFFFF"
            if k % 2
                == 0
            else "#F1F5F9"
        )
        draw.rectangle(
            (margin, current_y, width - margin, current_y + row_height),
            fill=row_fill,
        )
        current_x = margin
        values = [
            str(row.get("Ganhador", "—")),
            str(int(row.get(home_team)))
            if pd.notna(row.get(home_team))
            else "—",
            str(int(row.get(away_team)))
            if pd.notna(row.get(away_team))
            else "—",
            str(int(row.get("Qtd palpites", 0))),
        ]
        for value, (_, col_width) in zip(values, column_defs):
            draw.text(
                (current_x + 8, current_y + 10),
                truncate_text(draw, value, row_font, col_width - 16),
                font=row_font,
                fill="#0F172A",
            )
            current_x += col_width
        current_y += row_height

    draw.text(
        (margin, current_y + 12),
        "Distribuição de palpites por placar e vencedor/empate.",
        font=footer_font,
        fill="#475569",
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def create_game_predictions_image(
    player_table: pd.DataFrame, selected_game: pd.Series
) -> bytes:
    from PIL import Image, ImageDraw

    width = 1400
    margin = 40
    title_height = 120
    header_height = 56
    row_height = 54
    footer_height = 64
    height = (
        margin
        + title_height
        + header_height
        + row_height * max(1, len(player_table))
        + footer_height
        + margin
    )

    image = Image.new("RGB", (width, height), "#F8FAFC")
    draw = ImageDraw.Draw(image)

    title_font = load_image_font(size=40, bold=True)
    subtitle_font = load_image_font(size=20)
    header_font = load_image_font(size=22, bold=True)
    row_font = load_image_font(size=20)
    footer_font = load_image_font(size=18)

    draw.rounded_rectangle(
        (margin, margin, width - margin, margin + title_height - 10),
        radius=16,
        fill="#0F172A",
    )
    draw.text(
        (margin + 16, margin + 12),
        "Palpites individuais",
        font=title_font,
        fill="#FFFFFF",
    )
    draw.text(
        (margin + 16, margin + 60),
        f"{selected_game['Mandante']} x {selected_game['Visitante']} — {selected_game['Data'].strftime('%d/%m %H:%M')}",
        font=subtitle_font,
        fill="#CBD5E1",
    )

    current_y = margin + title_height
    current_x = margin
    column_defs = [
        ("Posição", 100),
        ("Palpite", 500),
        ("Placar", 160),
        ("Resultado", 220),
        ("Pontos", 120),
        ("Situação", 120),
    ]

    draw.rectangle(
        (margin, current_y, width - margin, current_y + header_height),
        fill="#1E293B",
    )
    for label, col_width in column_defs:
        draw.text(
            (current_x + 8, current_y + 12),
            label,
            font=header_font,
            fill="#FFFFFF",
        )
        current_x += col_width

    current_y += header_height
    for row in player_table.to_dict(orient="records"):
        row_fill = (
            "#FFFFFF"
            if (
                player_table.index.get_loc(
                    player_table[
                        player_table["Palpite"] == row["Palpite"]
                    ].index[0]
                )
                % 2
                == 0
            )
            else "#F1F5F9"
        )
        draw.rectangle(
            (margin, current_y, width - margin, current_y + row_height),
            fill=row_fill,
        )
        current_x = margin
        values = [
            str(int(row.get("Posição")))
            if pd.notna(row.get("Posição"))
            else "—",
            row.get("Palpite", "—"),
            row.get("Placar", "—"),
            row.get("Resultado Real", "—"),
            str(int(row.get("Pontos", 0)))
            if pd.notna(row.get("Pontos"))
            else "0",
            row.get("Situação", "—"),
        ]
        for value, (_, col_width) in zip(values, column_defs):
            draw.text(
                (current_x + 8, current_y + 12),
                truncate_text(draw, str(value), row_font, col_width - 16),
                font=row_font,
                fill="#0F172A",
            )
            current_x += col_width
        current_y += row_height

    draw.text(
        (margin, current_y + 12),
        "Posição atual de cada palpitador e resultados do jogo selecionado.",
        font=footer_font,
        fill="#475569",
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def format_ranking_text(
    ranking: pd.DataFrame,
    completed_games: int,
    total_games: int,
) -> str:
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    lines = [
        "🏆 Ranking Bolão Copa 2026",
        f"Atualizado em {generated_at}",
        f"Jogos: {completed_games}/{total_games}",
        "",
    ]
    for row in ranking.to_dict(orient="records"):
        lines.append(
            f"{int(row['Posição']):>2}º - {row['Palpite']}: "
            f"{int(row['Pontos'])} pts "
            f"({int(row['Acertos Placar'])} placar, "
            f"{int(row['Acertos Resultado'])} resultado)"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
