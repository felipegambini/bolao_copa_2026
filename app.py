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
    st.caption("Ranking, palpites individuais, evolução de pontos e atualização de resultados.")

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

    ranking_tab, individual_tab, evolution_tab, results_tab, editor_tab = st.tabs(
        [
            "Ranking",
            "Palpite individual",
            "Evolução",
            "Resultados",
            "Atualizar resultados",
        ]
    )

    with ranking_tab:
        render_ranking_tab(data.ranking)

    with individual_tab:
        render_individual_tab(data.palpites, data.ranking)

    with evolution_tab:
        render_evolution_tab(data.evolucao, data.ranking)

    with results_tab:
        render_results_tab(data.resultados)

    with editor_tab:
        render_results_editor_tab(data.resultados, results_path)


def render_sidebar() -> tuple[Path, Path]:
    st.sidebar.header("Arquivos")
    excel_path = Path(
        st.sidebar.text_input("Planilha de palpites", value=str(DEFAULT_EXCEL_PATH))
    )
    results_path = Path(
        st.sidebar.text_input("JSON de resultados", value=str(DEFAULT_RESULTS_PATH))
    )

    st.sidebar.divider()
    st.sidebar.markdown(
        "**Pontuação:** 3 pontos para placar exato e 1 ponto para vencedor/empate correto."
    )

    if st.sidebar.button("Recarregar dados", width='stretch'):
        st.cache_data.clear()
        st.rerun()

    return excel_path, results_path


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


def render_summary_metrics(ranking: pd.DataFrame, results: pd.DataFrame) -> None:
    completed_games = int(results["Jogo Realizado"].sum())
    pending_games = int((results["Status"] == "Pendente").sum())
    leader_points = int(ranking["Pontos"].max()) if not ranking.empty else 0
    last_completed = results.loc[results["Jogo Realizado"], "Data"].max()
    last_completed_label = (
        last_completed.strftime("%d/%m/%Y %H:%M")
        if pd.notna(last_completed)
        else "Sem jogos realizados"
    )

    col_participants, col_completed, col_pending, col_leader, col_last = st.columns(5)
    col_participants.metric("Participantes", f"{ranking['Palpite'].nunique():,}".replace(",", "."))
    col_completed.metric("Jogos realizados", completed_games)
    col_pending.metric("Jogos pendentes", pending_games)
    col_leader.metric("Pontos do líder", leader_points)
    col_last.metric("Último jogo pontuado", last_completed_label)


def render_ranking_tab(ranking: pd.DataFrame) -> None:
    st.subheader("Ranking de pontos por palpitador")
    st.dataframe(
        ranking,
        hide_index=True,
        width='stretch',
    )
    render_shareable_ranking(ranking)


def render_individual_tab(scored_predictions: pd.DataFrame, ranking: pd.DataFrame) -> None:
    st.subheader("Consulta de palpite individual")

    participants = ranking["Palpite"].tolist()
    selected_participant = st.selectbox("Palpitador", participants)

    participant_predictions = scored_predictions.loc[
        scored_predictions["Palpite"] == selected_participant,
        :,
    ].copy()

    status_filter = st.radio(
        "Filtro",
        ["Todos", "Jogos realizados", "Jogos pontuados", "Palpites inválidos"],
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
    elif status_filter == "Palpites inválidos":
        participant_predictions = participant_predictions.loc[
            ~participant_predictions["Palpite Valido"], :
        ]

    st.dataframe(
        format_prediction_table(participant_predictions),
        hide_index=True,
        width='stretch',
    )
    st.caption(
        "Legenda: ✅ placar cravado | 🟡 resultado correto | ❌ erro | "
        "⏳ aguardando resultado | ⚪ palpite incompleto."
    )


def render_shareable_ranking(ranking: pd.DataFrame) -> None:
    st.divider()
    st.subheader("Ranking para compartilhar")
    st.caption(
        "Imagem pronta para baixar e enviar no grupo, com todos os palpitadores."
    )

    ranking_image = create_ranking_image(ranking)
    generated_at = datetime.now().strftime("%Y%m%d_%H%M")

    st.image(ranking_image, caption="Prévia do ranking completo", width='stretch')
    st.download_button(
        "Baixar ranking em PNG",
        data=ranking_image,
        file_name=f"ranking_bolao_{generated_at}.png",
        mime="image/png",
        type="primary",
        width='stretch',
    )

    ranking_text = format_ranking_text(ranking)
    with st.expander("Ranking em texto para copiar"):
        st.code(ranking_text)
        st.download_button(
            "Baixar ranking em TXT",
            data=ranking_text.encode("utf-8"),
            file_name=f"ranking_bolao_{generated_at}.txt",
            mime="text/plain",
            width='stretch',
        )


def render_evolution_tab(evolution: pd.DataFrame, ranking: pd.DataFrame) -> None:
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
    st.line_chart(filtered_evolution, width='stretch')

    with st.expander("Ver tabela de evolução"):
        st.dataframe(
            filtered_evolution.reset_index().rename(columns={"Data": "Data/Hora"}),
            hide_index=True,
            width='stretch',
        )


def render_results_tab(results: pd.DataFrame) -> None:
    st.subheader("Resultados dos jogos")

    status_options = ["Todos", *sorted(results["Status"].dropna().unique().tolist())]
    selected_status = st.selectbox("Status", status_options)

    filtered_results = results.copy()
    if selected_status != "Todos":
        filtered_results = filtered_results.loc[filtered_results["Status"] == selected_status, :]

    st.dataframe(
        format_results_table(filtered_results),
        hide_index=True,
        width='stretch',
    )


def render_results_editor_tab(results: pd.DataFrame, results_path: Path) -> None:
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
            width='stretch',
            column_config={
                "Data": st.column_config.TextColumn("Data", help="Formato: dd/mm/aaaa"),
                "Horário": st.column_config.TextColumn("Horário", help="Formato: HH:MM"),
                "Mandante": st.column_config.TextColumn("Mandante"),
                "Visitante": st.column_config.TextColumn("Visitante"),
                "Placar Mandante": st.column_config.NumberColumn(
                    "Placar Mandante",
                    min_value=0,
                    step=1,
                    format="%d",
                ),
                "Placar Visitante": st.column_config.NumberColumn(
                    "Placar Visitante",
                    min_value=0,
                    step=1,
                    format="%d",
                ),
            },
        )
        submitted = st.form_submit_button("Salvar resultados e recalcular", type="primary")

    if not submitted:
        return

    try:
        save_results_from_editor(edited_results, results_path)
    except Exception as exc:
        st.error(f"Não foi possível salvar os resultados: {exc}")
        return

    st.cache_data.clear()
    st.success(f"Resultados salvos em `{results_path}`. Recalculando pontuação...")
    st.rerun()


def format_prediction_table(scored_predictions: pd.DataFrame) -> pd.DataFrame:
    formatted = scored_predictions.copy()
    formatted["Data/Hora"] = formatted["Data"].dt.strftime("%d/%m/%Y %H:%M")
    formatted["Semáforo"] = build_prediction_status(formatted)
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
            "Semáforo",
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
    status = pd.Series(
        "⏳ Aguardando",
        index=scored_predictions.index,
        dtype="string",
    )

    invalid_prediction = ~scored_predictions["Palpite Valido"].fillna(False)
    completed_game = scored_predictions["Jogo Realizado"].fillna(False)
    exact_score = scored_predictions["Acertou Placar"].fillna(False)
    correct_outcome = scored_predictions["Acertou Resultado"].fillna(False)

    status.loc[invalid_prediction] = "⚪ Palpite incompleto"
    status.loc[completed_game] = "❌ Erro"
    status.loc[completed_game & correct_outcome] = "🟡 Resultado correto"
    status.loc[completed_game & exact_score] = "✅ Placar cravado"
    status.loc[completed_game & invalid_prediction] = "⚪ Palpite incompleto"

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


def format_score_pair(home_scores: pd.Series, away_scores: pd.Series) -> pd.Series:
    home = home_scores.astype("Int64").astype("string").fillna("—")
    away = away_scores.astype("Int64").astype("string").fillna("—")
    return home + " x " + away


def create_ranking_image(ranking: pd.DataFrame) -> bytes:
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

    width = 1080
    margin = 40
    title_height = 100
    header_height = 42
    row_height = 34
    footer_height = 54
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

    title_font = load_image_font(size=34, bold=True)
    subtitle_font = load_image_font(size=18)
    header_font = load_image_font(size=18, bold=True)
    row_font = load_image_font(size=17)
    footer_font = load_image_font(size=15)

    draw.rounded_rectangle(
        (margin, margin, width - margin, margin + title_height - 12),
        radius=18,
        fill="#0F172A",
    )
    draw.text(
        (margin + 26, margin + 20),
        "Ranking Bolão Copa 2026",
        font=title_font,
        fill="#FFFFFF",
    )
    draw.text(
        (margin + 28, margin + 62),
        f"Atualizado em {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        font=subtitle_font,
        fill="#CBD5E1",
    )

    columns = [
        ("Pos.", "Posição", 82),
        ("Palpitador", "Palpite", 480),
        ("Pts", "Pontos", 90),
        ("Placar", "Acertos Placar", 130),
        ("Resultado", "Acertos Resultado", 180),
    ]

    current_y = margin + title_height
    current_x = margin
    draw.rectangle(
        (margin, current_y, width - margin, current_y + header_height),
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
    for row_number, row in enumerate(ranking_to_share.to_dict(orient="records")):
        row_fill = "#FFFFFF" if row_number % 2 == 0 else "#F1F5F9"
        if int(row["Posição"]) == 1:
            row_fill = "#FEF3C7"
        elif int(row["Posição"]) <= 3:
            row_fill = "#FFFBEB"

        draw.rectangle(
            (margin, current_y, width - margin, current_y + row_height),
            fill=row_fill,
        )

        current_x = margin
        for _, field_name, column_width in columns:
            value = str(row[field_name])
            if field_name == "Posição":
                value = f"{value}º"
            value = truncate_text(draw, value, row_font, column_width - 18)
            draw.text(
                (current_x + 12, current_y + 7),
                value,
                font=row_font,
                fill="#0F172A",
            )
            current_x += column_width

        current_y += row_height

    draw.rectangle((margin, current_y, width - margin, current_y + 1), fill="#CBD5E1")
    draw.text(
        (margin, current_y + 18),
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
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
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


def format_ranking_text(ranking: pd.DataFrame) -> str:
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    lines = [
        "🏆 Ranking Bolão Copa 2026",
        f"Atualizado em {generated_at}",
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
