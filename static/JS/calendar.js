// ---------- Utilities ----------
function parseDateISO(s){ const [y,m,d]=s.split('-').map(Number); return new Date(y,m-1,d); }
function toISODate(d){
    const y = d.getFullYear();
    const m = String(d.getMonth()+1).padStart(2,'0');
    const day = String(d.getDate()).padStart(2,'0');
    return `${y}-${m}-${day}`;
}


// ---------- Build exam map ----------
function buildExamMap(asignaturas){
    const map = new Map();
    const subjects = Object.keys(asignaturas);
    for(const s of subjects){
        const subj = asignaturas[s];
        if(!subj.examenes) continue;
        for(const ex of subj.examenes){
            const tipo = ex.tipo_examen || '';
            const dur = ex.duracion || '';
            for(const fh of (ex.fechas_horas||[])){
                const fecha = fh.fecha; const hora = fh.hora || '';
                const key = fecha;
                const item = {asignatura:s,tipo:tipo,duracion:dur,fecha:fecha,hora:hora};
                if(!map.has(key)) map.set(key,[]);
                map.get(key).push(item);
            }
        }
    }
    return map;
}

const examMap = buildExamMap(data);

// asignar colores
const palette = ["#f97316","#60a5fa","#34d399","#fb7185","#a78bfa","#f59e0b","#38bdf8","#f472b6","#84cc16","#60a5fa"];
const subjNames = Object.keys(data || {});
const subjColor = {};
subjNames.forEach((n,i)=> subjColor[n]= palette[i % palette.length]);

// render legend
const legendEl = document.getElementById('legend');
subjNames.forEach(n=>{
    const div = document.createElement('div'); div.className='legend-item';
    div.innerHTML = `<div class="color-dot" style="background:${subjColor[n]}"></div><div style="font-size:13px">${n}</div>`;
    legendEl.appendChild(div);
});

const legendItems = document.querySelectorAll('.legend-item');

legendItems.forEach(item => {
    const subj = item.querySelector('div:nth-child(2)').textContent;

    item.addEventListener('mouseenter', () => {
        // recorrer todas las badges del calendario
        document.querySelectorAll('.exam-badge').forEach(badge => {
            if(badge.textContent.startsWith(subj)) {
                badge.classList.add('highlighted');
                badge.classList.remove('dimmed');
            } else {
                badge.classList.add('dimmed');
                badge.classList.remove('highlighted');
            }
        });
    });

    item.addEventListener('mouseleave', () => {
        // quitar clases
        document.querySelectorAll('.exam-badge').forEach(badge => {
            badge.classList.remove('dimmed', 'highlighted');
        });
    });
});


// estado del calendario
let viewDate = new Date(2025,11,1);
const monthYearEl = document.getElementById('monthYear');
const calendarGrid = document.getElementById('calendarGrid');
const todayText = document.getElementById('todayText');
const currentInfo = document.getElementById('currentInfo');

function eliminarExamen(codigoFecha){
    fetch(`/eliminate/${encodeURIComponent(codigoFecha)}`, { method: 'POST' })
    .then(res => {
        if(!res.ok) throw new Error('Error eliminando examen');
        alert('Examen eliminado correctamente');
        renderWithAnimation('fade');
        generarExamenesPorEscoger();
    })
    .catch(err => {
        console.error(err);
        alert('No se pudo eliminar el examen');
    });
}

function sortExamsByTime(exams) {
    return exams.slice().sort((a,b)=>{
        const getStart = (h) => {
            if(!h) return 0;
            const [start] = h.split('-');
            const parts = start.split(':').map(Number);
            if(parts.length === 1) return parts[0]*60;
            return parts[0]*60 + (parts[1]||0);
        };
        return getStart(a.hora) - getStart(b.hora);
    });
}

// Render del calendario
function render(){
    calendarGrid.innerHTML='';
    const year = viewDate.getFullYear();
    const month = viewDate.getMonth();
    monthYearEl.textContent = viewDate.toLocaleString('es-ES',{month:'long',year:'numeric'}).replace(/\b\w/, c => c.toUpperCase());
    currentInfo.textContent = `${new Date().toLocaleDateString('es-ES')}`;
    todayText.textContent = `Hoy: ${new Date().toLocaleDateString('es-ES')}`;

    const first = new Date(year,month,1);
    const firstWeekday = (first.getDay() + 6) % 7; // 0=Monday
    const daysInMonth = new Date(year,month+1,0).getDate();
    const prevDays = firstWeekday;
    const totalCells = Math.ceil((prevDays + daysInMonth)/7)*7;
    const start = new Date(year,month,1 - prevDays);

    for(let i=0;i<totalCells;i++){
        const dt = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
        const cell = document.createElement('div');
        cell.className='day';
        if(dt.getMonth() !== month) cell.classList.add('inactive');
        const ds = toISODate(dt);
        const dayNumber = document.createElement('div'); dayNumber.className='day-number'; dayNumber.textContent = dt.getDate();
        cell.appendChild(dayNumber);

        const exams = sortExamsByTime(examMap.get(ds) || []);

        if(exams.length){
            const count = document.createElement('div'); count.className='exam-count'; count.textContent = exams.length + ' exam';
            cell.appendChild(count);
            exams.slice(0,2).forEach(ev=>{
                const b = document.createElement('div'); b.className='exam-badge';
                b.textContent = `${ev.asignatura} — ${ev.hora}`;
                b.style.background = subjColor[ev.asignatura] || '#999';
                b.style.color = '#061025';
                cell.appendChild(b);
            });
            cell.style.cursor='pointer';
            cell.addEventListener('click',()=>openModal(dt,exams));
        }

        calendarGrid.appendChild(cell);
    }
}

// Modal de exámenes por día
function openModal(date,exams){
    const tpl = document.getElementById('modalT');
    const clone = tpl.content.cloneNode(true);
    const modal = clone.querySelector('.modal');
    const title = clone.querySelector('#modalTitle');
    const content = clone.querySelector('#modalContent');
    title.textContent = `Exámenes — ${date.toLocaleDateString('es-ES')}`;
    content.innerHTML = '';
    sortExamsByTime(exams).forEach(ev => {
        const el = document.createElement('div'); 
        el.className='exam-item';
        el.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center">
                <div>
                    <strong style="text-transform:capitalize">${ev.asignatura}</strong>
                    <div class="meta">${ev.tipo ? ev.tipo : 'examen'} — ${ev.hora} — duración ${ev.duracion}</div>
                </div>
                <div style="display:flex;gap:8px;align-items:center">
                    <div style="width:12px;height:44px;background:${subjColor[ev.asignatura] || '#888'};border-radius:8px"></div>
                    <button class="delete-exam-btn" style="padding:2px 6px;font-size:12px;cursor:pointer">Eliminar</button>
                </div>
            </div>
        `;
        const btn = el.querySelector('.delete-exam-btn');
        btn.addEventListener('click', () => {
            const codigoFecha = `${ev.asignatura};${ev.hora};${ev.fecha}`;
            if(confirm(`¿Eliminar examen de ${ev.asignatura} el ${ev.fecha} a las ${ev.hora}?`)){
                eliminarExamen(codigoFecha);
            }
        });
        content.appendChild(el);
    });

    document.body.appendChild(clone);
    modal.querySelector('#closeModal').addEventListener('click',()=> modal.remove());
    modal.addEventListener('click',(e)=>{ if(e.target===modal) modal.remove() });
}

// --------- Animación del calendario ---------
function renderWithAnimation(direction){
    calendarGrid.classList.add(
        direction === 'left' ? 'slide-in-left' :
        direction === 'right' ? 'slide-in-right' :
        'fade-calendar'
    );

    setTimeout(()=>{
        render();
        calendarGrid.classList.remove('slide-in-left','slide-in-right','fade-calendar');
    }, 200);
}

// --------- Navegación botones ---------
document.getElementById('prev').addEventListener('click',()=>{ 
    viewDate.setMonth(viewDate.getMonth()-1);
    renderWithAnimation('left');
});
document.getElementById('next').addEventListener('click',()=>{ 
    viewDate.setMonth(viewDate.getMonth()+1); 
    renderWithAnimation('right');
});
document.getElementById('todayBtn').addEventListener('click',()=>{ 
    viewDate = new Date(); 
    renderWithAnimation('fade');
});

// --------- Render inicial ---------
render();
generarExamenesPorEscoger();

// Cerrar modal con ESC
document.addEventListener('keydown',(e)=>{ 
    if(e.key==='Escape'){ 
        const modal = document.querySelector('.modal'); 
        if(modal) modal.remove(); 
    }
});
