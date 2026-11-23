"""Sistema Académico - API + web. Las reglas viven en los triggers de la BD (academico.db)."""
import os, sqlite3
from contextlib import contextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DB_PATH", os.path.join(BASE, "academico.db"))
app = FastAPI(title="Sistema Académico")

@contextmanager
def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c; c.commit()                      # ACID: todo o nada
    except sqlite3.IntegrityError as e:
        c.rollback(); raise HTTPException(409, str(e))
    finally:
        c.close()

def rows(c, sql, *a): return [dict(r) for r in c.execute(sql, a)]

class Matricula(BaseModel): estudiante_id: int; seccion_id: int
class Nota(BaseModel):
    matricula_id: int; descripcion: str = Field(min_length=1)
    nota: float = Field(ge=0, le=10); peso: float = Field(gt=0, le=100)

@app.get("/api/resumen")
def resumen():
    with db() as c:
        one = lambda q: c.execute(q).fetchone()[0]
        return {"estudiantes": one("select count(*) from estudiante"),
                "secciones": one("select count(*) from seccion"),
                "matriculas": one("select count(*) from matricula where estado='INSCRITO'"),
                "promedio": one("select round(avg(nota_final),2) from matricula where nota_final is not null")}

@app.get("/api/estudiantes")
def estudiantes():
    with db() as c: return rows(c, "select * from estudiante order by apellidos, nombres")

class Est(BaseModel):
    cedula: str = Field(min_length=5); nombres: str = Field(min_length=1)
    apellidos: str = Field(min_length=1); email: str = Field(min_length=5)

@app.post("/api/estudiantes", status_code=201)
def nuevo_estudiante(b: Est):
    with db() as c:
        c.execute("insert into estudiante(cedula,nombres,apellidos,email) values(?,?,?,?)",
                  (b.cedula, b.nombres, b.apellidos, b.email))
    return {"ok": True}

@app.get("/api/secciones")
def secciones():
    with db() as c:
        s = rows(c, """select s.id, s.paralelo, s.cupo_max, m.codigo, m.nombre, m.creditos,
            d.nombres||' '||d.apellidos docente, a.codigo aula, a.capacidad, p.nombre periodo,
            (select count(*) from matricula x where x.seccion_id=s.id and x.estado='INSCRITO') inscritos
            from seccion s join materia m on m.id=s.materia_id join docente d on d.id=s.docente_id
            join aula a on a.id=s.aula_id join periodo p on p.id=s.periodo_id order by m.nombre""")
        for r in s:
            r["horarios"] = rows(c, "select id,dia,hora_inicio,hora_fin from horario where seccion_id=? order by dia,hora_inicio", r["id"])
            r["prerrequisitos"] = [x["nombre"] for x in rows(c, """select m.nombre from prerrequisito p join materia m on m.id=p.requisito_id
                where p.materia_id=(select materia_id from seccion where id=?)""", r["id"])]
        return s

class Hor(BaseModel):
    dia: int = Field(ge=1, le=7); hora_inicio: str; hora_fin: str

@app.put("/api/horarios/{hid}")
def cambiar_horario(hid: int, b: Hor):
    with db() as c:   # los triggers validan choques de aula y docente
        c.execute("update horario set dia=?, hora_inicio=?, hora_fin=? where id=?",
                  (b.dia, b.hora_inicio, b.hora_fin, hid))
    return {"ok": True}

@app.get("/api/matriculas")
def matriculas(estudiante_id: int | None = None):
    with db() as c:
        q = """select x.id, x.seccion_id, x.estado, x.nota_final, x.estudiante_id, e.nombres||' '||e.apellidos estudiante,
               m.nombre materia, m.codigo, s.paralelo from matricula x join estudiante e on e.id=x.estudiante_id
               join seccion s on s.id=x.seccion_id join materia m on m.id=s.materia_id"""
        r = rows(c, q + (" where x.estudiante_id=?" if estudiante_id else "") + " order by x.id desc",
                 *([estudiante_id] if estudiante_id else []))
        for m in r: m["notas"] = rows(c, "select descripcion,nota,peso from calificacion where matricula_id=?", m["id"])
        return r

@app.post("/api/matriculas", status_code=201)
def matricular(b: Matricula):
    with db() as c:
        c.execute("insert into matricula(estudiante_id,seccion_id) values(?,?)", (b.estudiante_id, b.seccion_id))
    return {"ok": True}

@app.delete("/api/matriculas/{mid}")
def retirar(mid: int):
    with db() as c: c.execute("update matricula set estado='RETIRADO' where id=? and estado='INSCRITO'", (mid,))
    return {"ok": True}

@app.post("/api/calificaciones", status_code=201)
def calificar(b: Nota):
    with db() as c:
        c.execute("insert into calificacion(matricula_id,descripcion,nota,peso) values(?,?,?,?)",
                  (b.matricula_id, b.descripcion, b.nota, b.peso))
    return {"ok": True}

@app.post("/api/secciones/{sid}/cerrar")
def cerrar(sid: int):
    with db() as c:   # nota >= 7 aprueba
        c.execute("""update matricula set estado=case when nota_final>=7 then 'APROBADO' else 'REPROBADO' end
                     where seccion_id=? and estado='INSCRITO' and nota_final is not null""", (sid,))
    return {"ok": True}

@app.delete("/api/estudiantes/{eid}")
def borrar_estudiante(eid: int):
    with db() as c:   # borra sus matrículas (y notas por cascada) y luego al estudiante
        c.execute("delete from matricula where estudiante_id=?", (eid,))
        c.execute("delete from estudiante where id=?", (eid,))
    return {"ok": True}

@app.delete("/api/secciones/{sid}")
def borrar_seccion(sid: int):
    with db() as c:   # horarios caen por cascada
        c.execute("delete from matricula where seccion_id=?", (sid,))
        c.execute("delete from seccion where id=?", (sid,))
    return {"ok": True}

@app.delete("/api/horarios/{hid}")
def borrar_horario(hid: int):
    with db() as c: c.execute("delete from horario where id=?", (hid,))
    return {"ok": True}

@app.get("/")
def home(): return FileResponse(os.path.join(BASE, "static", "index.html"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
