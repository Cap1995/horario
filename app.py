# app.py — Reservas 20 min con almuerzo (SQLite) + Exportación Excel profesional
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
FIN = time(18, 0)
BLOQUEO_INICIO = time(13, 0)
BLOQUEO_FIN = time(14, 0)
INTERVALO_MIN = 20
AUTOREFRESH_MS = 10_000  # 10 s

st.title("📅 Reservas de horas")
st.caption("Horario: 09:00–18:00 • Almuerzo sin reservas: 13:00–14:00 • Actualiza cada 10 s")

# ---------- DB ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reservas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,   -- ISO yyyy-mm-dd
            hora  TEXT NOT NULL,   -- HH:MM
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
    leer_reservas_dia.clear()
    leer_todas_reservas.clear()

# ---------- Excel profesional ----------
def build_excel_bytes(df: pd.DataFrame, titulo: str = "Reservas") -> bytes:
    """
    Genera un Excel .xlsx con estilos profesionales usando XlsxWriter y lo retorna en memoria (bytes).
    """
    # Asegurar columnas en orden deseado si existen
    cols = ["fecha", "hora", "nombre", "contacto", "comentario", "created_at"]
    df = df[[c for c in cols if c in df.columns]].copy()

    # Tipos para mejor formato
    # Convertir fecha/hora a objetos (si vienen como texto)
    if "fecha" in df.columns:
        # Mostrar como fecha
        df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce").dt.date
    if "hora" in df.columns:
        # Mantener texto HH:MM o interpretar como tiempo
        # Para Excel, lo dejamos como texto "HH:MM" para compatibilidad universal
        df["hora"] = df["hora"].astype(str)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        sheet_name = "Reservas"
        df.to_excel(writer, index=False, sheet_name=sheet_name, startrow=3)

        wb  = writer.book
        ws  = writer.sheets[sheet_name]

        # Estilos
        fmt_title = wb.add_format({
            "bold": True, "font_size": 16, "align": "left", "valign": "vcenter"
        })
        fmt_subtitle = wb.add_format({
            "italic": True, "font_size": 9, "font_color": "#666666"
        })
        fmt_header = wb.add_format({
            "bold": True, "bg_color": "#F2F2F2", "border": 1, "align": "center", "valign": "vcenter"
        })
        fmt_cell = wb.add_format({"border": 1})
        fmt_wrap = wb.add_format({"border": 1, "text_wrap": True})
        fmt_date = wb.add_format({"border": 1, "num_format": "yyyy-mm-dd"})
        fmt_small = wb.add_format({"font_size": 9, "font_color": "#666666"})

        # Título y subtítulo
        ws.merge_range("A1:F1", f"{titulo}", fmt_title)
        ws.write("A2", f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", fmt_subtitle)

        # Encabezados con formato
        for col_idx, col_name in enumerate(df.columns):
            ws.write(3, col_idx, col_name.capitalize(), fmt_header)

        # Bordes a todo el rango de datos
        n_rows, n_cols = df.shape
        if n_rows > 0:
            ws.conditional_format(4, 0, 4 + n_rows - 1, n_cols - 1, {
                "type": "no_errors", "format": fmt_cell
            })

        # Anchos de columna y formatos por columna
        col_widths = {
            "fecha": 12,
            "hora": 8,
            "nombre": 28,
            "contacto": 26,
            "comentario": 42,
            "created_at": 20
        }
        for col_idx, col_name in enumerate(df.columns):
            width = col_widths.get(col_name, 18)
            ws.set_column(col_idx, col_idx, width)
            # Aplicar formatos específicos
            if col_name == "fecha":
                ws.set_column(col_idx, col_idx, width, fmt_date)
            elif col_name == "comentario":
                ws.set_column(col_idx, col_idx, width, fmt_wrap)

        # Autofiltro
        ws.autofilter(3, 0, 3 + n_rows, n_cols - 1)

        # Footer simple
        ws.write(4 + n_rows + 1, 0, "Exportado desde la app de reservas (SQLite).", fmt_small)

    output.seek(0)
    return output.read()

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

st.divider()
st.subheader("Reservas del día")
if not df_dia.empty:
    mostrar = df_dia.sort_values("hora")[["hora", "nombre", "contacto", "comentario", "created_at"]]
    mostrar.index = range(1, len(mostrar) + 1)
    st.dataframe(mostrar, use_container_width=True, height=320)

    # Botón directo para exportar Excel profesional
    df_all = leer_todas_reservas()
    xlsx_bytes = build_excel_bytes(df_all, titulo="Reservas (todas las fechas)")
    st.download_button(
        "📥 Descargar Excel de reservas",
        data=xlsx_bytes,
        file_name="reservas.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
else:
    st.write("No hay reservas para esta fecha.")


st.caption("Nota: En Streamlit Cloud el disco es efímero; para persistencia confiable usa una BD gestionada (p. ej., Postgres en Neon/Supabase/Railway).")
