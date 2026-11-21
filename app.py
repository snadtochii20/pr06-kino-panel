import sqlite3
from contextlib import closing
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

DB = Path(__file__).with_name("kino.db")


@st.cache_data(show_spinner=False)
def load_data(years, directors, show_tags):
    selected = """
        SELECT id, title, year, director, duration_min
        FROM films
        WHERE year BETWEEN ? AND ?
    """
    if directors:
        placeholders = ", ".join("?" for _ in directors)
        selected += f" AND director IN ({placeholders})"
    params = (*years, *directors)

    with closing(sqlite3.connect(DB)) as conn:
        films = pd.read_sql_query(
            f"""WITH selected AS ({selected})
            SELECT f.*, EXISTS (
                SELECT 1 FROM tags AS t WHERE t.film_id = f.id
            ) AS has_tag
            FROM selected AS f ORDER BY year, title, id""",
            conn, params=params,
        )
        views = pd.read_sql_query(
            f"""WITH selected AS ({selected})
            SELECT v.viewed_on, v.viewers
            FROM views AS v JOIN selected AS f ON f.id = v.film_id""",
            conn, params=params,
        )
        tags = None
        if show_tags:
            tags = pd.read_sql_query(
                f"""WITH selected AS ({selected})
                SELECT t.id, t.film_id, f.title, t.tag, t.kind, t.weight
                FROM tags AS t JOIN selected AS f ON f.id = t.film_id
                ORDER BY t.id DESC""",
                conn, params=params,
            )
    return films, views, tags


st.set_page_config(page_title="PY-C3U · Кінопанель", layout="wide")
st.title("PY-C3U · Кінопанель")

with closing(sqlite3.connect(DB)) as conn:
    directors = [row[0] for row in conn.execute(
        "SELECT DISTINCT director FROM films ORDER BY director"
    )]

with st.sidebar:
    years = st.slider("Роки випуску", 1890, 2100, (1930, 1969))
    selected_directors = st.multiselect("Режисери", directors)
    show_tags = st.checkbox("Показати сирі рядки тегів")

films, views, tags = load_data(years, tuple(sorted(selected_directors)), show_tags)

st.session_state.setdefault("tags_added", 0)
st.session_state.setdefault("last_tag", "")
if st.session_state.last_tag:
    st.success(
        f"Останній тег: {st.session_state.last_tag}. "
        f"Додано за сесію: {st.session_state.tags_added}."
    )

left, right = st.columns(2)
left.metric("Фільмів у вибірці", len(films))
share = f"{films['has_tag'].mean():.2%}" if len(films) else "—"
right.metric("Частка фільмів із тегами", share)

data_tab, charts_tab = st.tabs(["Дані", "Графіки"])

with data_tab:
    if films.empty:
        st.info("Для вибраних фільтрів фільмів немає.")
    else:
        st.dataframe(
            films[["title", "year", "director", "duration_min"]],
            hide_index=True,
        )
        labels = {
            row.id: f"{row.title} ({row.year})"
            for row in films.itertuples(index=False)
        }

        with st.form("add_tag"):
            st.subheader("Додати тег")
            film_id = st.selectbox("Фільм", list(labels), format_func=labels.__getitem__)
            tag = st.text_input("Тег")
            kind = st.selectbox("Тип тегу", ["жанр", "тема", "настрій"])
            weight = st.number_input("Вага", min_value=1, value=1, step=1)
            submitted = st.form_submit_button("Додати")

        if submitted:
            clean_tag = tag.strip()
            if not clean_tag:
                st.error("Введи назву тегу.")
            else:
                try:
                    with closing(sqlite3.connect(DB)) as conn, conn:
                        conn.execute("PRAGMA foreign_keys = ON")
                        conn.execute(
                            "INSERT INTO tags (film_id, tag, kind, weight) VALUES (?, ?, ?, ?)",
                            (int(film_id), clean_tag, kind, int(weight)),
                        )
                except sqlite3.Error as error:
                    st.error(f"Не вдалося зберегти тег: {error}")
                else:
                    st.session_state.tags_added += 1
                    st.session_state.last_tag = clean_tag
                    load_data.clear()
                    st.rerun()

    if show_tags:
        st.subheader("Сирі рядки тегів")
        st.dataframe(tags, hide_index=True)

with charts_tab:
    if views.empty:
        st.info("Для цієї вибірки немає переглядів.")
    else:
        st.subheader("Накопичені глядачі за місяцями")
        months = pd.to_datetime(views["viewed_on"]).dt.to_period("M")
        month_range = pd.period_range(months.min(), months.max(), freq="M")
        monthly = views.groupby(months)["viewers"].sum()
        cumulative = monthly.reindex(month_range, fill_value=0).cumsum()
        cumulative.index = cumulative.index.to_timestamp()
        cumulative.index.name = "Місяць"
        st.area_chart(cumulative.rename("Глядачі"))

        st.subheader("Кількість глядачів на один перегляд")
        fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
        ax.hist(views["viewers"], bins=15, color="#365ba0", edgecolor="white")
        ax.set_xlabel("Глядачів за один перегляд")
        ax.set_ylabel("Кількість переглядів")
        st.pyplot(fig)
        plt.close(fig)
