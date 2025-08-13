# app.py — Reservas 20 min con almuerzo (SQLite) + descargas
import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, date, time, timedelta
import os

# Auto-refresh opcional
try:
    from streamlit_autorefresh import st_autorefresh
    _HAS_AUTOREFRESH = True
except Exception:
    _HAS_AUTOREFRESH = False

st.set_page_config(page_title="Reservas 20 minutos", page_icon="⏰", layout="centered")

# ---------- Configuración ----------
DB_PATH = "reservas.db"
INICIO = time(9, 0)
FIN = time(18, 0)
BLOQUEO_INICIO = time(13, 0)
BLOQUEO_FIN = time(14, 0)
INTERVALO_MIN = 20
AUTOREFRESH_MS = 10_000  # 10 s

st.title("📅 Reservas en intervalos de 20 minutos")
st.caption("Horario: 09:00–18:00 • Almuerzo sin reservas: 13:00–14:00 • Actualiza cada 10 s")

# ---------- DB ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reservas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            hora  TEXT NOT NULL,
            nombre TEXT NOT NULL,
            contacto TEXT,
            comentario TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(fecha, hora)
        )
    """)
    return conn

def agregar_reserva(fecha:str, hora:str, nombre:str, contacto:str, comentario:str) -> bool:
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO reservas (fecha, hora, nombre, contacto, comentario, created_at) VALUES (?,?,?,?,?,?)",
                (fecha, hora, nombre, contacto, comentario, datetime.now().isoformat(timespec="seconds"))
            )
        return True
    except sqlite3.IntegrityError:
        # Violación UNIQUE(fecha, hora)
        return False

@st.cache_data(show_spinner=False)
def leer_reservas_dia(fecha:str) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT fecha, hora, nombre, contacto, comentario, created_at FROM reservas WHERE fecha = ?",
            conn, params=(fecha,)
        )
    return df

@st.cache_data(show_spinner=False)
def leer_todas_reservas() -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT fecha, hora, nombre, contacto, comentario, created_at FROM reservas ORDER BY fecha, hora",
            conn
        )
    return df

def borrar_reservas_dia(fecha:str):
    with get_conn() as conn:
        conn.execute("DELETE FROM reservas WHERE fecha = ?", (fecha,))
    # limpiar cache
    leer_reservas_dia.clear()
    leer_todas_reservas.clear()

# ---------- Lógica de slots ----------
def generar_slots(d: date):
    slots = []
    t = datetime.combine(d, INICIO)
    fin_dt = datetime.combine(d, FIN)
    while t <= fin_dt:
        h = t.time()
        if not (BLOQUEO_INICIO <= h < BLOQUEO_FIN):
            slots.append(h.strftime("%H:%M"))
        t += timedelta(minutes=INTERVALO_MIN)
    # no exceder FIN
    return [s for s in slots if s <= FIN.strftime("%H:%M")]

# ---------- UI ----------
if _HAS_AUTOREFRESH:
    st_autorefresh(interval=AUTOREFRESH_MS, key="autorefresh")
else:
    st.caption("🔄 Auto-actualización deshabilitada (instala streamlit-autorefresh para activarla).")

hoy = date.today()
fecha = st.date_input("Selecciona una fecha", value=hoy, min_value=hoy)
fecha_str = fecha.isoformat()

df_dia = leer_reservas_dia(fecha_str)
ocupadas = set(df_dia["hora"].tolist())
todos_slots = generar_slots(fecha)
disponibles = [s for s in todos_slots if s not in ocupadas]

col1, col2 = st.columns(2)
with col1:
    st.subheader("Disponibles")
    if disponibles:
        st.write(", ".join(disponibles))
    else:
        st.info("No hay horarios disponibles para esta fecha.")
with col2:
    st.subheader("Ocupadas")
    if ocupadas:
        st.write(", ".join(sorted(ocupadas)))
    else:
        st.write("—")

st.divider()
st.subheader("Tomar una hora")
with st.form("form_reserva", clear_on_submit=True):
    slot = st.selectbox("Horario", options=disponibles, placeholder="Elige un horario")
    nombre = st.text_input("Nombre", max_chars=80)
    contacto = st.text_input("Contacto (teléfono o email, opcional)", max_chars=120)
    comentario = st.text_area("Comentario (opcional)", max_chars=300, height=80)
    enviar = st.form_submit_button("Reservar", use_container_width=True)
    if enviar:
        if not slot:
            st.warning("Selecciona un horario disponible.")
        elif not nombre.strip():
            st.warning("Ingresa tu nombre.")
        else:
            ok = agregar_reserva(fecha_str, slot, nombre.strip(), contacto.strip(), comentario.strip())
            if ok:
                st.success(f"Reserva confirmada para el {fecha_str} a las {slot}.")
                # invalidar cache para ver el nuevo estado
                leer_reservas_dia.clear()
                df_dia = leer_reservas_dia(fecha_str)
            else:
                st.error("Ese horario acaba de ser tomado por otra persona. Intenta con otro.")

st.divider()
st.subheader("Reservas del día")
if not df_dia.empty:
    mostrar = df_dia.sort_values("hora")[["hora", "nombre", "contacto", "comentario", "created_at"]]
    mostrar.index = range(1, len(mostrar) + 1)
    st.dataframe(mostrar, use_container_width=True, height=320)
else:
    st.write("No hay reservas para esta fecha.")

with st.expander("⚙️ Opciones (admin mínimo)"):
    st.caption("Estas acciones afectan el archivo local SQLite `reservas.db`.")
    colA, colB, colC = st.columns(3)

    # Descargar CSV de TODO
    with colA:
        if st.button("Generar CSV", use_container_width=True):
            df_all = leer_todas_reservas()
            csv = df_all.to_csv(index=False, encoding="utf-8")
            st.download_button("Descargar reservas.csv", data=csv, file_name="reservas.csv",
                               mime="text/csv", use_container_width=True)

    # Borrar el día seleccionado
    with colB:
        if st.button("Vaciar reservas de la fecha", type="secondary", use_container_width=True):
            borrar_reservas_dia(fecha_str)
            st.success(f"Reservas del {fecha_str} borradas.")

    # Descargar el archivo .db completo
    with colC:
        if os.path.exists(DB_PATH):
            with open(DB_PATH, "rb") as f:
                st.download_button("Descargar reservas.db", data=f.read(),
                                   file_name="reservas.db", mime="application/octet-stream",
                                   use_container_width=True)
        else:
            st.info("No existe base de datos aún.")

st.caption("Nota: En Streamlit Cloud el disco es efímero; para persistencia confiable usa una BD gestionada (p. ej., Postgres en Neon/Supabase/Railway).")
