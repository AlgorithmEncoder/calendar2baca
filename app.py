# archivo: app.py
from flask import Flask, render_template, request, jsonify, redirect, url_for
import json
from datetime import date, timedelta, datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
from copy import deepcopy
from math import sqrt

# Configuración de Outlook
SMTP_SERVER = 'smtp.office365.com'
SMTP_PORT = 587
EMAIL_USER = os.environ.get('EMAIL_USER')
EMAIL_PASS = os.environ.get('EMAIL_PASS')
DESTINATARIOS = ['persona1@outlook.com', 'persona2@outlook.com']  # lista de destinatarios
CLAVE_ADMIN = os.environ.get("ADMIN_KEY")
CLAVE_MAESTRA = os.environ.get("MASTER_KEY")
print(">>> DEBUG ENV:", {
    "EMAIL_USER": repr(os.environ.get("EMAIL_USER")),
    "EMAIL_PASS": repr(os.environ.get("EMAIL_PASS")),
    "ADMIN_KEY": repr(os.environ.get("ADMIN_KEY")),
    "MASTER_KEY": repr(os.environ.get("MASTER_KEY")),
})


def enviar_correo(asunto, cuerpo, destinatarios=DESTINATARIOS):
    """
    Envía un correo con asunto y cuerpo a la lista de destinatarios.
    """
    if not EMAIL_USER or not EMAIL_PASS:
        print("Credenciales de correo no configuradas")
        return
    
    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = ', '.join(destinatarios)
    msg['Subject'] = asunto
    msg.attach(MIMEText(cuerpo, 'html'))  # puedes usar 'plain' si no quieres HTML

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, destinatarios, msg.as_string())
        server.quit()
        print(f"Correo enviado a {destinatarios}")
    except Exception as e:
        print("Error al enviar correo:", e)

def algoritmo_recomendacion_un_ex(fechas_posibles: list, examen_estudiado: tuple, DB):
    """
    fechas_posibles: lista de dicts {'fecha': 'YYYY-MM-DD', 'hora': 'HH:MM-HH:MM'} (como viene de tu frontend)
    examen_estudiado: tupla (None, momento_id_opcional, peso_asignatura_opcional)
       - aceptamos que el primer campo sea None (la fecha todavía no existe)
       - el segundo puede ser un momento (id) o None
       - el tercero es el peso de la asignatura (si lo tienes), si no lo tienes se puede extraer del DB
    DB: estructura JSON con 'asignaturas' y 'momentos' (igual que has mostrado)

    Devuelve: lista de tuplas (fecha, puntuacion) donde puntuacion es 0..100 (mayor = mejor)
    """

    momentos = DB['momentos']
    asignaturas = DB['asignaturas']

    # ---------- utilidades ----------
    def get_day(fecha: str) -> str:
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        fecha_dt = datetime.strptime(fecha, "%Y-%m-%d")
        return dias[fecha_dt.weekday()]

    def desviacion_tipica(lista: list):
        if len(lista) <= 1:
            return 0.0
        mean = sum(lista) / len(lista)
        var = sum((x - mean) ** 2 for x in lista) / len(lista)
        return var  # se aplica sqrt al usarla en penalizaciones

    # ---------- penalizaciones ----------
    def penalizacion_ex_seguidos(examenes_fecha: list, p=0.5):
        """
        examenes_fecha: [(fecha, momento_id, peso_asig), ...]
        Cuenta momentos con índices consecutivos (momento_id numerico contiguo).
        """
        if not examenes_fecha:
            return 0.0
        try:
            momentos_idxs = sorted(int(ex[1]) for ex in examenes_fecha if ex[1] is not None)
        except Exception:
            # si algún momento no es convertible a int, no penalizamos por consecutivos
            return 0.0

        n_ex_seguidos = 0
        for i in range(1, len(momentos_idxs)):
            if momentos_idxs[i] == momentos_idxs[i-1] + 1:
                n_ex_seguidos += 1

        # resultado suave: si 0 -> 0, si >=1 -> potencia para penalizar crecimientos
        return (n_ex_seguidos ** n_ex_seguidos) * p if n_ex_seguidos > 0 else 0.0

    def penalizacion_desequilibrio_dias(lista_dias: list, p=0.5):
        var = desviacion_tipica(lista_dias)
        return p * sqrt(var)

    def penalizacion_desequilibrio_semanas(lista_semanas: list, p=0.5):
        var = desviacion_tipica(lista_semanas)
        return p * sqrt(var)

    def penalizacion_cercania_ex_pesados(fechas:dict, p=0.5):
        """
        Penaliza si exámenes pesados están demasiado cerca en el tiempo.
        fechas: {fecha: [ (fecha, momento, peso), ... ]}
        """
        
        # Obtener lista de exámenes
        examenes = []
        for lista in fechas.values():
            examenes.extend(lista)

        def diferencia_dias(f1, f2):
            d1 = datetime.strptime(f1, "%Y-%m-%d").date()
            d2 = datetime.strptime(f2, "%Y-%m-%d").date()
            return abs((d1 - d2).days)

        penalizacion = 0

        for i in range(len(examenes)):
            f1, _, p1 = examenes[i]
            for j in range(i + 1, len(examenes)):
                f2, _, p2 = examenes[j]

                dias = diferencia_dias(f1, f2)

                # Cuanto más cerca estén, mayor penalización
                if dias == 0:
                    factor = 4
                elif dias == 1:
                    factor = 2
                elif dias == 2:
                    factor = 1
                else:
                    factor = 0.2  # casi no penaliza si están bien separados

                penalizacion += (p1 * p2) * factor

        return penalizacion * p

    # ---------- funciones de agrupación ----------
    def ordenar_calendario_en_dias():
        """
        Recorre DB['asignaturas'] y devuelve:
            { 'YYYY-MM-DD': [ (fecha, momento_id, peso_asig), ... ], ... }
        donde peso_asig es el valor de "peso" de la asignatura para ese tipo de examen (no multiplicado por peso momento).
        """
        dias = {}

        for asig_name, asig_data in asignaturas.items():
            pesos_asig = asig_data.get('peso', [0.0])
            tipos_asig = asig_data.get('tipo_examen', [])

            for ex in asig_data.get('examenes', []):
                tipo_ex = ex.get('tipo_examen', None)
                # elegir índice de peso: si hay tipos, buscar el índice; si no, usar 0
                if tipos_asig and tipo_ex in tipos_asig:
                    idx = tipos_asig.index(tipo_ex)
                else:
                    idx = 0
                peso_asig = pesos_asig[idx] if idx < len(pesos_asig) else pesos_asig[0]

                for fh in ex.get('fechas_horas', []):
                    fecha = fh.get('fecha')
                    hora = fh.get('hora')
                    if not fecha or not hora:
                        continue

                    # buscar el momento que tenga la misma hora y día
                    momento_id = None
                    dia_nombre = get_day(fecha)
                    for m_id, m_info in momentos.items():
                        if m_info.get('hora') == hora and m_info.get('dia') == dia_nombre:
                            momento_id = m_id
                            break

                    # si no encontramos momento por hora+dia, intentar por hora solamente
                    if momento_id is None:
                        for m_id, m_info in momentos.items():
                            if m_info.get('hora') == hora:
                                momento_id = m_id
                                break

                    # Guardamos (fecha, momento_id, peso_asig)
                    if fecha not in dias:
                        dias[fecha] = []
                    dias[fecha].append((fecha, momento_id, peso_asig))
        return dias

    def dividir_en_semanas(dict_dias: dict):
        """
        Agrupa dict_dias (fecha -> info) en semanas ISO.
        Devuelve lista de semanas ordenada: [ {fecha: info, ...}, ... ]
        """
        semanas_map = {}
        for fecha_str, info in dict_dias.items():
            # aceptar que info sea cualquier cosa (peso numérico o lista)
            fecha_dt = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            weeknum = fecha_dt.isocalendar().week
            year = fecha_dt.isocalendar().year
            key = (year, weeknum)
            if key not in semanas_map:
                semanas_map[key] = {}
            semanas_map[key][fecha_str] = info
        # devolver semanas ordenadas por (year, week)
        ordered_keys = sorted(semanas_map.keys())
        return [semanas_map[k] for k in ordered_keys]

    # ---------- main ----------
    # calendario base de exámenes (fecha -> list of (fecha, momento_id, peso_asig) )
    dias_calendario = ordenar_calendario_en_dias()

    resultados = []  # (fecha_opcion, peso_total)

    # Para cada fecha posible (se espera dict con 'fecha' y 'hora')
    for opcion in fechas_posibles:
        if isinstance(opcion, dict):
            fecha_op = opcion.get('fecha')
            hora_op = opcion.get('hora')
        else:
            # aceptar también strings por compatibilidad
            fecha_op = opcion
            hora_op = None

        if not fecha_op:
            continue

        # calcular momento_id de la opción (si usuario envía hora, mejor)
        momento_op = None
        if hora_op:
            dia_nombre = get_day(fecha_op)
            for m_id, m_info in momentos.items():
                if m_info.get('hora') == hora_op and m_info.get('dia') == dia_nombre:
                    momento_op = m_id
                    break
            if momento_op is None:
                for m_id, m_info in momentos.items():
                    if m_info.get('hora') == hora_op:
                        momento_op = m_id
                        break

        # Deep copy del calendario base para simular añadir el examen
        dias = deepcopy(dias_calendario)

        # obtener peso_asig del examen_estudiado si viene; si no, usar examen_estudiado[1] como asignatura? 
        # Suponemos examen_estudiado = (None, momento_id_optional, peso_asig_optional)
        peso_estudiado = examen_estudiado[2] if len(examen_estudiado) > 2 and examen_estudiado[2] is not None else None
        momento_estudiado = examen_estudiado[1] if len(examen_estudiado) > 1 else None

        # preferir momento calculado por la opción (hora), si no, usar el proporcionado
        momento_final = momento_op or momento_estudiado

        if fecha_op not in dias:
            dias[fecha_op] = []

        # si no tenemos peso del examen nuevo, intentar inferirlo desde DB buscando una asignatura con ese momento (no ideal).
        if peso_estudiado is None:
            # no sabemos la asignatura aquí: dejamos peso 1.0 por defecto
            peso_estudiado = 1.0

        # añadir examen simulado en formato (fecha, momento_id, peso_asig)
        dias[fecha_op].append((fecha_op, momento_final, peso_estudiado))

        # ---- calcular peso por día ----
        peso_por_dia = {}
        for dia, exs in dias.items():
            suma = 0.0
            for ex in exs:
                _, mom, peso_asig = ex
                if mom is None or mom not in momentos:
                    peso_momento = 1.0  # si no hay momento, asumimos peso neutro 1.0
                else:
                    peso_momento = momentos[mom]['peso']
                suma += peso_asig * peso_momento
            # añadir penalización por exámenes seguidos en ese día (pasamos la lista original exs)
            suma += penalizacion_ex_seguidos(exs)
            peso_por_dia[dia] = suma

        # ---- agrupar por semanas tanto pesos como exámenes ----
        semanas_pesos = dividir_en_semanas(peso_por_dia)      # lista de dicts fecha->peso
        semanas_exams = dividir_en_semanas(dias)              # lista de dicts fecha-> [exams...]

        # Asegurar que ambas listas tengan la misma longitud y correspondencia por orden ISO
        pesos_semanas = []
        for idx, semana in enumerate(semanas_pesos):
            # suma de la semana (pesos de los días)
            sum_sem = sum(semana.values()) if semana else 0.0

            # lista de pesos por día (para desviación)
            lista_pesos_dias = list(semana.values())

            # obtener la misma semana en semanas_exams (si existe)
            week_exams = semanas_exams[idx] if idx < len(semanas_exams) else {}

            pen_dias = penalizacion_desequilibrio_dias(lista_pesos_dias)
            pen_cercania = penalizacion_cercania_ex_pesados(week_exams)
            peso_semana = sum_sem + pen_dias + pen_cercania

            pesos_semanas.append(peso_semana)

        # ---- peso total (todas las semanas) más penalización de desequilibrio entre semanas ----
        peso_total = sum(pesos_semanas) + penalizacion_desequilibrio_semanas(pesos_semanas)

        resultados.append((fecha_op, peso_total))

    # ---- convertir pesos a puntuaciones 0..100 (mayor = mejor, invertimos porque menor peso = mejor) ----
    if not resultados:
        return []

    pesos = [p for _, p in resultados]
    peso_max = max(pesos)
    peso_min = min(pesos)

    puntuaciones = []
    # Si todos los pesos son iguales, dar 50 a todos
    if abs(peso_max - peso_min) < 1e-9:
        for fecha, _ in resultados:
            puntuaciones.append((fecha, 50.0))
    else:
        # Normalizar: 100 * (1 - (peso - min)/(max - min)) para que menor peso => puntuación mayor
        for fecha, peso in resultados:
            score = 100.0 * (1.0 - (peso - peso_min) / (peso_max - peso_min))
            puntuaciones.append((fecha, round(score, 2)))

    # ordenar por puntuación descendente (mejor primero)
    puntuaciones.sort(key=lambda x: x[1], reverse=True)
    return puntuaciones

app = Flask(__name__)

# -----------------------------
# Cargar y guardar base de datos
# -----------------------------
def cargar_db():
    with open('datos.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def guardar_db(db):
    with open('datos.json', 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

DB = cargar_db()

# -----------------------------
# RUTA PRINCIPAL → CALENDARIO
# -----------------------------
@app.route('/')
def index():
    asigns = DB['asignaturas']
    moms = DB['momentos']

    # calcular número total de exámenes
    exams_count = sum(len(a['examenes']) for a in asigns.values())

    return render_template(
        'calendario.html',  # ← nuevo archivo HTML
        asignaturas=asigns,
        asignaturas_json=json.dumps(asigns),
        examenes=json.dumps(DB['asignaturas']),  # para JS
        exams_count=exams_count,
        momentos = moms
    )

# -----------------------------
# API: momentos por asignatura
# -----------------------------
@app.route('/api/momentos/<asignatura>')
def api_momentos(asignatura):
    if asignatura not in DB['asignaturas']:
        return jsonify({'error': 'asignatura desconocida'}), 404

    moment_ids = DB['asignaturas'][asignatura].get('momentos', [])
    detalles = {k: v for k, v in DB['momentos'].items() if k in moment_ids}

    hoy = date.today()
    fin = hoy + timedelta(days=60)
    fechas_disponibles = []

    for d in range((fin - hoy).days + 1):
        dia_actual = hoy + timedelta(days=d)
        dia_semana = dia_actual.weekday()

        for m in moment_ids:
            if dia_semana == int(m[0]):
                fechas_disponibles.append({
                    'codigo': m,
                    'fecha': dia_actual.isoformat(),
                    'hora': detalles[m]['hora']
                })

    return jsonify({
        'momentos': moment_ids,
        'detalles': detalles,
        'fechas_disponibles': fechas_disponibles
    })

# -----------------------------
# REGISTRO DE EXÁMENES
# -----------------------------
@app.route('/registrar', methods=['POST'])
def registrar():
    form = request.form
    asignatura = form.get('asignatura')

    if not asignatura or asignatura not in DB['asignaturas']:
        return "Asignatura inválida", 400

    asign_obj = DB['asignaturas'][asignatura]
    tipos_asign = asign_obj.get('tipo_examen', [])

    # determinar tipo de examen
    if len(tipos_asign) == 0:
        tipo = 'corriente'
    else:
        tipo = form.get('tipo_examen_final', '').strip()
        if not tipo:
            return 'Tipo de examen inválido', 400

    # recoger fechas/hora
    seleccion = form.getlist('seleccion_momentos')
    fechas_horas = []

    for s in seleccion:
        codigo, fecha = s.split('-', 1)
        if codigo not in asign_obj['momentos']:
            return f"Momento inválido: {codigo}", 400
        fechas_horas.append({
            'fecha': fecha,
            'hora': DB['momentos'][codigo]['hora']
        })

    duracion = form.get('duracion')
    if duracion not in ('1h', '1:30', '2h'):
        return "Duración inválida", 400

    examen = {
        'tipo_examen': tipo,
        'fechas_horas': fechas_horas,
        'duracion': duracion
    }

    DB['asignaturas'][asignatura]['examenes'].append(examen)
    guardar_db(DB)
    
    # ---------- CORREO INFORMATIVO ------------
    asunto = f"Nuevo examen registrado: {asignatura} ({tipo})"
    cuerpo = f"""
    <h2>Se ha registrado un nuevo examen</h2>
    <p><strong>Asignatura:</strong> {asignatura}</p>
    <p><strong>Tipo de examen:</strong> {tipo}</p>
    <p><strong>Duración:</strong> {duracion}</p>
    <p><strong>Fechas y horas:</strong></p>
    <ul>
    """
    for fh in fechas_horas:
        cuerpo += f"<li>{fh['fecha']} a las {fh['hora']}</li>"
    cuerpo += "</ul>"
    
    enviar_correo(asunto, cuerpo)

    return redirect(url_for('index'))

# -----------------------------
# ELIMINAR EXAMEN
# -----------------------------
@app.post("/verificar_clave")
def verificar_clave():
    data = request.get_json()
    clave = data.get("clave")

    return jsonify({"ok": clave == CLAVE_ADMIN or clave == CLAVE_MAESTRA})

@app.post("/verificar_clave_maestra")
def verificar_clave_maestra():
    data = request.get_json()
    clave = data.get("clave")

    return jsonify({"ok": clave == CLAVE_MAESTRA})

@app.route("/eliminate/<codigoFecha>", methods=['POST'])
def eliminar_examen(codigoFecha):
    """
    codigoFecha llega como:
        asignatura;hora;fechaISO
    Ejemplo:
        'Matemáticas;08:00-09:00;2025-12-03'
    """
    try:
        asignatura, hora, fecha = codigoFecha.split(';')
    except ValueError:
        return "Código inválido", 400

    if asignatura not in DB['asignaturas']:
        return "Asignatura no encontrada", 404

    asign_obj = DB['asignaturas'][asignatura]
    examenes = asign_obj.get('examenes', [])

    eliminado = False

    # buscar dentro de los exámenes de la asignatura
    for ex in examenes[:]:
        nuevas_fechas = [
            fh for fh in ex.get('fechas_horas', [])
            if not (fh['fecha'] == fecha and fh['hora'] == hora)
        ]

        if len(nuevas_fechas) != len(ex['fechas_horas']):
            # Se eliminó una fecha
            eliminado = True
            ex['fechas_horas'] = nuevas_fechas

            # Si el examen quedó sin fechas → eliminar examen completo
            if not nuevas_fechas:
                examenes.remove(ex)

    if not eliminado:
        return "No se encontró el examen a eliminar", 404

    guardar_db(DB)

    # ---- Enviar correo ----
    asunto = f"Examen eliminado: {asignatura}"
    cuerpo = f"""
    <h2>Se ha eliminado una fecha de examen</h2>
    <p><strong>Asignatura:</strong> {asignatura}</p>
    <p><strong>Fecha eliminada:</strong> {fecha}</p>
    <p><strong>Hora:</strong> {hora}</p>
    """

    enviar_correo(asunto, cuerpo)

    return redirect(url_for('index'))

@app.route("/buscar_mejor_dia/<exam_id>", methods=["GET"])
def buscar_mejor_dia(exam_id):
    # Buscar el examen en examChoices (o en DB)
    try:
        asignatura_name, fecha, hora = exam_id.split(";")
    except ValueError:
        return jsonify({"error": "ID inválido"}), 400

    exam = None
    for ex in DB['asignaturas'].get(asignatura_name, {}).get('examenes', []):
        for fh in ex.get('fechas_horas', []):
            if fh['fecha'] == fecha and fh['hora'] == hora:
                exam = ex
                break
        if exam:
            break

    if not exam:
        return jsonify({"error": "Examen no encontrado"}), 404

    # Construir fechas_posibles
    fechas_posibles = exam.get('fechas_horas', [])

    if not fechas_posibles:
        return jsonify({"error": "No hay fechas disponibles"}), 400

    # Obtener peso del examen
    asig_data = DB['asignaturas'][asignatura_name]
    tipos = asig_data.get("tipo_examen", [])
    pesos = asig_data.get("peso", [1.0])
    tipo_examen = exam.get("tipo_examen") or "corriente"
    idx = tipos.index(tipo_examen) if tipos and tipo_examen in tipos else 0
    peso_asig = pesos[idx] if idx < len(pesos) else pesos[0]

    # Preparar examen_estudiado
    examen_estudiado = (None, None, peso_asig)

    # Llamar al algoritmo
    puntuaciones = algoritmo_recomendacion_un_ex(
        fechas_posibles=fechas_posibles,
        examen_estudiado=examen_estudiado,
        DB=DB
    )

    # Devolver todas las fechas con puntuación
    ranking = [{"fecha": f, "hora": next((fh['hora'] for fh in fechas_posibles if fh['fecha'] == f), ""), "score": int(score)} for f, score in puntuaciones]

    # Ordenar de mayor a menor score
    ranking.sort(key=lambda x: x['score'], reverse=True)

    return jsonify({"ranking": ranking})

@app.post("/limpiar_calendario")
def limpiar_calendario_route():
    for asignatura in DB['asignaturas']:
        asignatura['examenes'] = []
    guardar_db(DB)
    return jsonify({"ok": True, "mensaje": "Calendario limpiado"})



# -----------------------------
if __name__ == '__main__':
    app.run()
