# app.py — Reservas 20 min (SQLite) + fechas acotadas + viernes 15/08 hasta 13:00
# Vista de reservas protegida con clave + Excel profesional

import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, date, time, timedelta
import os
from io import BytesIO

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
FIN_DEF = time(18, 0)
BLOQUEO_INICIO = time(13, 0)  # almuerzo
BLOQUEO_FIN = time(14, 0)     # almuerzo
INTERVALO_MIN = 20
AUTOREFRESH_MS = 10_000  # 10 s

# Fechas permitidas (ajústalas a tu necesidad)
ALLOWED_DATES = sorted({
    date(2025, 8, 19),  # martes 19/08/2025 (solo hasta 13:00)
    date(2025, 8, 20),  # miercoles 19/08/2025
    date(2025, 8, 21),  # jueves 20/08/2025
    date(2025, 8, 22),  # viernes 21/08/2025
})
FRIDAY_SHORT_DAY = date(2025, 8, 22)  # este viernes termina a las 13:00

# Clave admin para ver reservas (configurable en secrets)
ADMIN_KEY = st.secrets.get("ADMIN_KEY", "admin123")

# ---------- DB ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reservas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,   -- ISO yyyy-mm-dd
            hora  TEXT NOT NULL,   -- HH:MM
            nombre TEXT NOT NULL,  -- aquí guardamos "Nombre y Apellido"
            contacto TEXT,
            comentario TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(fecha, hora)
        )
    """)
    return conn

def agregar_reserva(fecha:str, hora:str, nombre:str) -> bool:
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO reservas (fecha, hora, nombre, contacto, comentario, created_at) VALUES (?,?,?,?,?,?)",
                (fecha, hora, nombre, "", "", datetime.now().isoformat(timespec="seconds"))
            )
        return True
    except sqlite3.IntegrityError:
        return False

@st.cache_data(show_spinner=False)
def leer_reservas_dia(fecha:str) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT fecha, hora, nombre, created_at FROM reservas WHERE fecha = ? ORDER BY hora",
            conn, params=(fecha,)
        )
    return df

@st.cache_data(show_spinner=False)
def leer_todas_reservas() -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT fecha, hora, nombre, created_at FROM reservas ORDER BY fecha, hora",
            conn
        )
    return df

# ---------- Excel profesional ----------
def build_excel_bytes(df: pd.DataFrame, titulo: str = "Reservas") -> bytes:
    cols = ["fecha", "hora", "nombre", "created_at"]
    df = df[[c for c in cols if c in df.columns]].copy()
    if "fecha" in df.columns:
        df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce").dt.date
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        sheet = "Reservas"
        # Dejamos espacio para título (fila 1-2) y encabezados en fila 4 (index 3)
        start_row = 4
        df.to_excel(writer, index=False, sheet_name=sheet, startrow=start_row)
        wb, ws = writer.book, writer.sheets[sheet]

        fmt_title = wb.add_format({"bold": True, "font_size": 16, "align": "left", "valign": "vcenter"})
        fmt_subtitle = wb.add_format({"italic": True, "font_size": 9, "font_color": "#666666"})
        fmt_header = wb.add_format({"bold": True, "bg_color": "#F2F2F2", "border": 1, "align": "center", "valign": "vcenter"})
        fmt_cell = wb.add_format({"border": 1})
        fmt_date = wb.add_format({"border": 1, "num_format": "yyyy-mm-dd"})
        fmt_small = wb.add_format({"font_size": 9, "font_color": "#666666"})

        # Título y subtítulo
        ws.merge_range("A1:D1", titulo, fmt_title)
        ws.write("A2", f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", fmt_subtitle)

        # Reestilizar encabezados (fila 5 visual; index 4) y bordes
        n_rows, n_cols = df.shape
        for c in range(n_cols):
            ws.write(start_row, c, df.columns[c].capitalize(), fmt_header)

        if n_rows > 0:
            ws.conditional_format(start_row + 1, 0, start_row + n_rows, n_cols - 1,
                                  {"type": "no_errors", "format": fmt_cell})

        # Anchos/formatos
        widths = {"fecha": 12, "hora": 8, "nombre": 28, "created_at": 20}
        for c in range(n_cols):
            col_name = df.columns[c]
            ws.set_column(c, c, widths.get(col_name, 18), fmt_date if col_name == "fecha" else None)

        # Autofiltro
        ws.autofilter(start_row, 0, start_row + max(n_rows, 1), n_cols - 1)
        # Footer
        ws.write(start_row + n_rows + 2, 0, "Exportado desde la app de reservas (SQLite).", fmt_small)

    output.seek(0)
    return output.read()

# ---------- Helpers ----------
DIAS_ES = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]
def nombre_dia(d: date) -> str:
    return DIAS_ES[d.weekday()]

def fin_para_fecha(d: date) -> time:
    return time(13, 0) if d == FRIDAY_SHORT_DAY else FIN_DEF

def generar_slots(d: date):
    fin_time = fin_para_fecha(d)
    slots = []
    t = datetime.combine(d, INICIO)
    fin_dt = datetime.combine(d, fin_time)
    while t <= fin_dt:
        h = t.time()
        # Excluir bloque almuerzo [13:00,14:00)
        if not (BLOQUEO_INICIO <= h < BLOQUEO_FIN):
            slots.append(h.strftime("%H:%M"))
        t += timedelta(minutes=INTERVALO_MIN)
    return [s for s in slots if s <= fin_time.strftime("%H:%M")]

def format_fecha(d: date) -> str:
    return f"{nombre_dia(d).capitalize()} {d.strftime('%d-%m-%Y')}"

# ---------- UI ----------
if _HAS_AUTOREFRESH:
    st_autorefresh(interval=AUTOREFRESH_MS, key="autorefresh")
else:
    st.caption("🔄 Auto-actualización deshabilitada (instala streamlit-autorefresh para activarla).")

st.title("📅 Revisición descriptores de cargo")
st.caption("Reserve su horario")

# Selección de fecha SOLO entre las permitidas
st.subheader("Selecciona la fecha")
fecha = st.selectbox("Fecha disponible", options=ALLOWED_DATES, format_func=format_fecha)
fecha_str = fecha.isoformat()

# Estado del día y slots
df_dia = leer_reservas_dia(fecha_str)
ocupadas = set(df_dia["hora"].tolist())
todos_slots = generar_slots(fecha)
disponibles = [s for s in todos_slots if s not in ocupadas]

# Formulario: SOLO Nombre y Apellido
st.divider()
st.subheader("Tomar una hora")
with st.form("form_reserva", clear_on_submit=True):
    slot = st.selectbox("Horario", options=disponibles, placeholder="Elige un horario")
    nombre = st.text_input("Nombre y Apellido", max_chars=80)
    enviar = st.form_submit_button("Reservar", use_container_width=True)
    if enviar:
        if not slot:
            st.warning("Selecciona un horario disponible.")
        elif not nombre.strip():
            st.warning("Ingresa tu Nombre y Apellido.")
        else:
            ok = agregar_reserva(fecha_str, slot, nombre.strip())
            if ok:
                st.success(f"Reserva confirmada para el {format_fecha(fecha)} a las {slot}.")
                leer_reservas_dia.clear()
                df_dia = leer_reservas_dia(fecha_str)
            else:
                st.error("Ese horario acaba de ser tomado por otra persona. Intenta con otro.")

# Sección protegida: ver reservas del día + Excel
st.divider()
st.subheader("Reservas del día (sección protegida)")

if "authed" not in st.session_state:
    st.session_state.authed = False

if not st.session_state.authed:
    with st.form("auth_form"):
        clave = st.text_input("Clave de acceso", type="password")
        inc = st.form_submit_button("Ingresar", use_container_width=True)
    if inc:
        if clave == ADMIN_KEY:
            st.session_state.authed = True
            st.success("✅ Acceso concedido.")
        else:
            st.error("❌ Clave incorrecta.")
else:
    # Tabla
    if not df_dia.empty:
        mostrar = df_dia.sort_values("hora")[["hora", "nombre", "created_at"]]
        mostrar.index = range(1, len(mostrar) + 1)
        st.dataframe(mostrar, use_container_width=True, height=320)
    else:
        st.info("No hay reservas para esta fecha.")

    # Botón único: Excel profesional (todas las fechas)
    df_all = leer_todas_reservas()
    xlsx_bytes = build_excel_bytes(df_all, titulo="Reservas (todas las fechas)")
    st.download_button(
        "📥 Descargar Excel de reservas",
        data=xlsx_bytes,
        file_name="reservas.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
