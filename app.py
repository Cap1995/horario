# app.py — Reservas cada 20 minutos con almuerzo 13:00–14:00 (bloqueado)
# Persistencia local en CSV y auto-actualización

import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
import os
from io import StringIO
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Reservas 20 minutos", page_icon="⏰", layout="centered")

# ---------- Configuración ----------
ARCHIVO_RESERVAS = "reservas.csv"
INICIO = time(9, 0)
FIN = time(18, 0)
BLOQUEO_INICIO = time(13, 0)  # almuerzo
BLOQUEO_FIN = time(14, 0)     # almuerzo
INTERVALO_MIN = 20
AUTOREFRESH_MS = 10_000  # 10 s

st.title("📅 Reservas en intervalos de 20 minutos")
st.caption("Horario: 09:00–18:00 • Almuerzo sin reservas: 13:00–14:00 • Actualiza cada 10 s")

# ---------- Utilidades ----------
@st.cache_data(show_spinner=False)
def cargar_reservas():
    """Carga el CSV (o lo crea si no existe). Devuelve DataFrame con columnas estándar."""
    if not os.path.exists(ARCHIVO_RESERVAS):
        df = pd.DataFrame(columns=["fecha", "hora", "nombre", "contacto", "comentario", "created_at"])
        df.to_csv(ARCHIVO_RESERVAS, index=False, encoding="utf-8")
        return df

    try:
        df = pd.read_csv(ARCHIVO_RESERVAS, dtype=str, encoding="utf-8")
    except Exception:
        # Recuperación simple si hay caracteres extraños
        contenido = open(ARCHIVO_RESERVAS, "r", encoding="utf-8", errors="ignore").read()
        df = pd.read_csv(StringIO(contenido), dtype=str)

    for col in ["fecha", "hora", "nombre", "contacto", "comentario", "created_at"]:
        if col not in df.columns:
            df[col] = ""
    return df.fillna("")


def guardar_reserva_segura(nueva_fila: dict) -> bool:
    """Guarda una reserva si el slot sigue libre. Escritura atómica y limpieza de cache."""
    # 1) Cargar sin cache para evitar estado viejo
    if os.path.exists(ARCHIVO_RESERVAS):
        df = pd.read_csv(ARCHIVO_RESERVAS, dtype=str, encoding="utf-8").fillna("")
    else:
        df = pd.DataFrame(columns=["fecha", "hora", "nombre", "contacto", "comentario", "created_at"])

    # 2) Verificar disponibilidad aún libre
    ya_tomada = ((df["fecha"] == nueva_fila["fecha"]) & (df["hora"] == nueva_fila["hora"])).any()
    if ya_tomada:
        return False

    # 3) Agregar y escribir a un archivo temporal, luego reemplazar
    df = pd.concat([df, pd.DataFrame([nueva_fila])], ignore_index=True)
    tmp = ARCHIVO_RESERVAS + ".tmp"
    df.to_csv(tmp, index=False, encoding="utf-8")
    os.replace(tmp, ARCHIVO_RESERVAS)

    # 4) Limpiar cache de lectura
    cargar_reservas.clear()
    return True


def generar_slots(d: date):
    """Genera slots de 20 min entre INICIO y FIN excluyendo el bloque de almuerzo."""
    slots = []
    t = datetime.combine(d, INICIO)
    fin_dt = datetime.combine(d, FIN)
    while t <= fin_dt:
        h = t.time()
        # Excluir bloque de almuerzo [13:00, 14:00)
        if not (BLOQUEO_INICIO <= h < BLOQUEO_FIN):
            slots.append(h.strftime("%H:%M"))
        t += timedelta(minutes=INTERVALO_MIN)

    # Asegurar no exceder FIN (por formato string)
    slots = [s for s in slots if s <= FIN.strftime("%H:%M")]
    return slots


# ---------- UI ----------
# Autorefresh cada 10 s con extra_streamlit_components
st_autorefresh(interval=AUTOREFRESH_MS, key="autorefresh")

hoy = date.today()
fecha = st.date_input("Selecciona una fecha", value=hoy, min_value=hoy)
fecha_str = fecha.isoformat()

df = cargar_reservas()
df_dia = df[df["fecha"] == fecha_str].copy()

# Estado de ocupación
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
            registro = {
                "fecha": fecha_str,
                "hora": slot,
                "nombre": nombre.strip(),
                "contacto": contacto.strip(),
                "comentario": comentario.strip(),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            ok = guardar_reserva_segura(registro)
            if ok:
                st.success(f"Reserva confirmada para el {fecha_str} a las {slot}.")
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
    st.caption("Estas acciones afectan solo el archivo local `reservas.csv`.")
    colA, colB = st.columns(2)

    with colA:
        # Ofrecer descarga del CSV actual si existe
        if os.path.exists(ARCHIVO_RESERVAS):
            with open(ARCHIVO_RESERVAS, "rb") as f:
                st.download_button(
                    "Descargar reservas.csv",
                    data=f,
                    file_name="reservas.csv",
                    mime="text/csv",
                    use_container_width=True
                )
        else:
            st.info("No existe archivo de reservas aún.")

    with colB:
        borrar = st.button("Vaciar reservas del día seleccionado", type="secondary", use_container_width=True)
        if borrar:
            if os.path.exists(ARCHIVO_RESERVAS):
                df_all = pd.read_csv(ARCHIVO_RESERVAS, dtype=str, encoding="utf-8").fillna("")
                df_all = df_all[df_all["fecha"] != fecha_str]  # elimina solo la fecha seleccionada
                tmp = ARCHIVO_RESERVAS + ".tmp"
                df_all.to_csv(tmp, index=False, encoding="utf-8")
                os.replace(tmp, ARCHIVO_RESERVAS)
                cargar_reservas.clear()
                st.success(f"Reservas del {fecha_str} borradas.")
            else:
                st.info("No existe archivo de reservas aún.")

st.caption("Consejo: Para multiusuario real en producción, usa una base de datos (SQLite/PostgreSQL) y bloqueos transaccionales.")
