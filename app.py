
import os
import io
import csv
import uuid
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path

import qrcode
from flask import (
    Flask, request, redirect, url_for, session,
    send_file, send_from_directory, render_template_string, abort
)
from werkzeug.utils import secure_filename

app = Flask(__name__)

# CONFIGURAÇÃO PARA TESTE LOCAL
USUARIO_ERP = "admin"
SENHA_ERP = "123456"

app.secret_key = os.environ.get(
    "SECRET_KEY", "apenas-para-teste-local-nao-publicar"
)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

BASE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("DB_PATH", str(BASE / "motores.db")))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(BASE / "fotos")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

STATUS = [
    "Disponível",
    "Em uso",
    "Para assistência",
    "Em assistência",
    "Baixado"
]


def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conexao():
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def iniciar_banco():
    with conexao() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS motores (
                id TEXT PRIMARY KEY,
                tag TEXT,
                fabricante TEXT,
                modelo TEXT,
                potencia REAL,
                corrente REAL,
                tensao REAL,
                local TEXT,
                condicao TEXT,
                status TEXT,
                foto TEXT,
                data_cadastro TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS historico (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                motor_id TEXT NOT NULL,
                status_anterior TEXT,
                status_novo TEXT,
                local TEXT,
                responsavel TEXT,
                observacao TEXT,
                data TEXT,
                FOREIGN KEY(motor_id) REFERENCES motores(id)
            )
        """)


iniciar_banco()


def autenticado(f):
    @wraps(f)
    def interno(*args, **kwargs):
        if not session.get("usuario"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return interno


HTML = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ERP Motores</title>
<style>
* {box-sizing:border-box}
body {
    margin:0;
    background:#f1f5f9;
    font-family:Arial,sans-serif;
    color:#172033;
}
header {
    background:#10243d;
    color:white;
    padding:17px 22px;
    display:flex;
    justify-content:space-between;
    align-items:center;
    flex-wrap:wrap;
    gap:12px;
}
header a {color:white;text-decoration:none}
main {max-width:1200px;margin:auto;padding:20px}
nav {
    display:flex;
    gap:8px;
    flex-wrap:wrap;
    margin-bottom:20px;
}
nav a,.btn,button {
    background:#1463ba;
    color:white;
    border:0;
    padding:11px 15px;
    border-radius:8px;
    text-decoration:none;
    cursor:pointer;
    font-size:14px;
}
.card {
    background:white;
    border-radius:12px;
    padding:20px;
    margin-bottom:18px;
    box-shadow:0 2px 10px #0000000c;
}
input,select,textarea {
    width:100%;
    padding:11px;
    margin:6px 0 13px;
    border:1px solid #cbd5e1;
    border-radius:7px;
    font-size:15px;
}
label {font-size:13px;font-weight:bold}
table {width:100%;border-collapse:collapse}
th,td {
    padding:11px;
    border-bottom:1px solid #e2e8f0;
    text-align:left;
    font-size:13px;
}
.table-wrap {overflow-x:auto}
.grid {
    display:grid;
    grid-template-columns:repeat(4,1fr);
    gap:12px;
}
.kpi {
    background:white;
    border-radius:10px;
    padding:18px;
    text-align:center;
}
.kpi strong {
    display:block;
    font-size:28px;
    color:#1463ba;
}
.status {font-weight:bold}
img.foto {max-width:250px;border-radius:9px}
#reader {max-width:500px}
small {color:#64748b}
@media(max-width:700px){
    .grid {grid-template-columns:repeat(2,1fr)}
    main {padding:12px}
    header {padding:14px}
    table {min-width:700px}
}
</style>
</head>
<body>
<header>
<strong>⚙ ERP DE MOTORES</strong>
{% if session.get('usuario') %}
<span>{{session.usuario}} | <a href="/logout">Sair</a></span>
{% endif %}
</header>
<main>
{% if session.get('usuario') %}
<nav>
<a href="/">Dashboard</a>
<a href="/novo">Cadastrar motor</a>
<a href="/scanner">Ler QR Code</a>
<a href="/exportar">Exportar Excel CSV</a>
</nav>
{% endif %}
{{conteudo|safe}}
</main>
</body>
</html>
"""


def pagina(conteudo, **dados):
    interno = render_template_string(conteudo, **dados)
    return render_template_string(HTML, conteudo=interno)


@app.route("/login", methods=["GET", "POST"])
def login():
    erro = ""

    if request.method == "POST":
        usuario = request.form.get("usuario", "")
        senha = request.form.get("senha", "")

        if usuario == USUARIO_ERP and senha == SENHA_ERP:
            session.clear()
            session["usuario"] = usuario
            return redirect("/")

        erro = "Usuário ou senha inválidos."

    return pagina("""
    <div class="card" style="max-width:400px;margin:50px auto">
    <h2>Acesso ao ERP</h2>
    <p style="color:red">{{erro}}</p>
    <form method="post">
    <label>Usuário</label>
    <input name="usuario" required>
    <label>Senha</label>
    <input name="senha" type="password" required>
    <button>Entrar</button>
    </form>
    </div>
    """, erro=erro)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
@autenticado
def dashboard():
    with conexao() as db:
        motores = db.execute(
            "SELECT * FROM motores ORDER BY data_cadastro DESC"
        ).fetchall()

    contagem = {s: 0 for s in STATUS}

    for m in motores:
        if m["status"] in contagem:
            contagem[m["status"]] += 1

    return pagina("""
    <h2>Controle de Motores Elétricos</h2>
    <div class="grid">
    <div class="kpi">Total<strong>{{motores|length}}</strong></div>
    {% for nome,valor in contagem.items() %}
    <div class="kpi">{{nome}}<strong>{{valor}}</strong></div>
    {% endfor %}
    </div>

    <div class="card">
    <h3>Inventário de motores</h3>
    <input id="busca"
           placeholder="Pesquisar motor, TAG ou local"
           oninput="filtrar()">
    <div class="table-wrap">
    <table id="tabela">
    <thead>
    <tr>
    <th>ID</th><th>TAG</th><th>Potência</th>
    <th>Corrente</th><th>Local</th>
    <th>Condição</th><th>Status</th><th>Ação</th>
    </tr>
    </thead>
    <tbody>
    {% for m in motores %}
    <tr>
    <td>{{m.id[:8]}}</td>
    <td>{{m.tag or '-'}}</td>
    <td>{{m.potencia}} kW</td>
    <td>{{m.corrente}} A</td>
    <td>{{m.local}}</td>
    <td>{{m.condicao}}</td>
    <td class="status">{{m.status}}</td>
    <td><a href="/motor/{{m.id}}">Abrir</a></td>
    </tr>
    {% endfor %}
    </tbody>
    </table>
    </div>
    </div>

    <script>
    function filtrar(){
        let q=document.getElementById('busca').value.toLowerCase();
        document.querySelectorAll('#tabela tbody tr').forEach(tr=>{
            tr.style.display=
                tr.innerText.toLowerCase().includes(q)?'':'none';
        });
    }
    </script>
    """, motores=motores, contagem=contagem)


@app.route("/novo", methods=["GET", "POST"])
@autenticado
def novo():
    if request.method == "POST":
        motor_id = str(uuid.uuid4())
        foto_nome = ""

        foto = request.files.get("foto")

        if foto and foto.filename:
            extensao = os.path.splitext(
                secure_filename(foto.filename)
            )[1].lower()

            if extensao not in [".jpg", ".jpeg", ".png", ".webp"]:
                abort(400, "Formato de foto inválido")

            foto_nome = motor_id + extensao
            foto.save(UPLOAD_DIR / foto_nome)

        local = request.form.get("local", "").strip()
        condicao = request.form.get("condicao", "Usado")

        if condicao not in ("Novo", "Usado") or not local:
            abort(400)

        try:
            potencia = float(request.form.get("potencia") or 0)
            corrente = float(request.form.get("corrente") or 0)
            tensao = float(request.form.get("tensao") or 0)
        except ValueError:
            abort(400, "Valores elétricos inválidos")

        with conexao() as db:
            db.execute("""
                INSERT INTO motores VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                motor_id,
                request.form.get("tag", ""),
                request.form.get("fabricante", ""),
                request.form.get("modelo", ""),
                potencia,
                corrente,
                tensao,
                local,
                condicao,
                "Disponível",
                foto_nome,
                agora()
            ))

            db.execute("""
                INSERT INTO historico
                (motor_id,status_anterior,status_novo,local,
                 responsavel,observacao,data)
                VALUES (?,?,?,?,?,?,?)
            """, (
                motor_id, "", "Disponível", local,
                session["usuario"], "Cadastro inicial", agora()
            ))

        return redirect(url_for("motor", motor_id=motor_id))

    return pagina("""
    <div class="card">
    <h2>Cadastrar motor</h2>
    <form method="post" enctype="multipart/form-data">

    <label>TAG do motor</label>
    <input name="tag" required>

    <label>Fabricante</label>
    <input name="fabricante">

    <label>Modelo</label>
    <input name="modelo">

    <label>Potência (kW)</label>
    <input type="number" step="any" min="0"
           name="potencia" required>

    <label>Corrente (A)</label>
    <input type="number" step="any" min="0"
           name="corrente" required>

    <label>Tensão (V)</label>
    <input type="number" step="any" min="0" name="tensao">

    <label>Local de armazenamento ou instalação</label>
    <input name="local" required>

    <label>Condição</label>
    <select name="condicao">
    <option>Novo</option>
    <option>Usado</option>
    </select>

    <label>Foto do motor</label>
    <input type="file" name="foto" accept="image/*">

    <button>Cadastrar e gerar QR Code</button>
    </form>
    </div>
    """)


@app.route("/motor/<motor_id>")
@autenticado
def motor(motor_id):
    with conexao() as db:
        m = db.execute(
            "SELECT * FROM motores WHERE id=?", (motor_id,)
        ).fetchone()

        historico = db.execute("""
            SELECT * FROM historico
            WHERE motor_id=? ORDER BY id DESC
        """, (motor_id,)).fetchall()

    if not m:
        abort(404)

    return pagina("""
    <div class="card">
    <h2>Motor {{m.tag}}</h2>
    <p><b>ID:</b> {{m.id}}</p>
    <p><b>Fabricante:</b> {{m.fabricante}}</p>
    <p><b>Modelo:</b> {{m.modelo}}</p>
    <p><b>Potência:</b> {{m.potencia}} kW</p>
    <p><b>Corrente:</b> {{m.corrente}} A</p>
    <p><b>Tensão:</b> {{m.tensao}} V</p>
    <p><b>Local:</b> {{m.local}}</p>
    <p><b>Condição:</b> {{m.condicao}}</p>
    <p><b>Status:</b> {{m.status}}</p>
    <p><b>Cadastro:</b> {{m.data_cadastro}}</p>

    {% if m.foto %}
    <img class="foto" src="/foto/{{m.foto}}">
    {% endif %}

    <h3>QR Code do motor</h3>
    <img src="/qr/{{m.id}}" width="190">
    <p><small>O QR Code identifica este motor no ERP.</small></p>
    </div>

    <div class="card">
    <h3>Movimentar motor</h3>
    <form method="post" action="/movimentar/{{m.id}}">

    <label>Novo status</label>
    <select name="status">
    {% for s in status %}
    <option {% if s==m.status %}selected{% endif %}>
    {{s}}</option>
    {% endfor %}
    </select>

    <label>Local / setor</label>
    <input name="local" value="{{m.local}}" required>

    <label>Observação</label>
    <textarea name="observacao"
      placeholder="Motivo da movimentação"></textarea>

    <button>Registrar movimentação</button>
    </form>
    </div>

    <div class="card">
    <h3>Histórico de movimentações</h3>
    <div class="table-wrap">
    <table>
    <tr>
    <th>Data</th><th>Anterior</th><th>Novo</th>
    <th>Local</th><th>Responsável</th><th>Observação</th>
    </tr>
    {% for h in historico %}
    <tr>
    <td>{{h.data}}</td>
    <td>{{h.status_anterior}}</td>
    <td>{{h.status_novo}}</td>
    <td>{{h.local}}</td>
    <td>{{h.responsavel}}</td>
    <td>{{h.observacao}}</td>
    </tr>
    {% endfor %}
    </table>
    </div>
    </div>
    """, m=m, historico=historico, status=STATUS)


@app.route("/movimentar/<motor_id>", methods=["POST"])
@autenticado
def movimentar(motor_id):
    novo_status = request.form.get("status")
    novo_local = request.form.get("local", "").strip()

    if novo_status not in STATUS or not novo_local:
        abort(400)

    with conexao() as db:
        m = db.execute(
            "SELECT * FROM motores WHERE id=?", (motor_id,)
        ).fetchone()

        if not m:
            abort(404)

        db.execute("""
            UPDATE motores SET status=?,local=? WHERE id=?
        """, (novo_status, novo_local, motor_id))

        db.execute("""
            INSERT INTO historico
            (motor_id,status_anterior,status_novo,local,
             responsavel,observacao,data)
            VALUES (?,?,?,?,?,?,?)
        """, (
            motor_id,
            m["status"],
            novo_status,
            novo_local,
            session["usuario"],
            request.form.get("observacao", ""),
            agora()
        ))

    return redirect(url_for("motor", motor_id=motor_id))


@app.route("/qr/<motor_id>")
@autenticado
def qr(motor_id):
    with conexao() as db:
        m = db.execute(
            "SELECT id FROM motores WHERE id=?", (motor_id,)
        ).fetchone()

    if not m:
        abort(404)

    endereco = url_for(
        "motor", motor_id=motor_id, _external=True
    )

    imagem = qrcode.make(endereco)
    buffer = io.BytesIO()
    imagem.save(buffer, format="PNG")
    buffer.seek(0)

    return send_file(buffer, mimetype="image/png")


@app.route("/foto/<nome>")
@autenticado
def foto(nome):
    return send_from_directory(UPLOAD_DIR, nome)


@app.route("/scanner")
@autenticado
def scanner():
    return pagina("""
    <div class="card">
    <h2>Leitor de QR Code</h2>
    <p>Aponte a câmera para o QR Code do motor.</p>

    <div id="reader"></div>
    <p id="resultado"></p>
    <button onclick="iniciar()">Iniciar câmera</button>

    <p><small>
    O navegador precisa de HTTPS para usar
    a câmera no celular.
    </small></p>
    </div>

    <script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>
    <script>
    let scanner=null;

    async function iniciar(){
        try {
            scanner=new Html5Qrcode("reader");

            await scanner.start(
                {facingMode:"environment"},
                {fps:10,qrbox:250},
                async function(texto){
                    await scanner.stop();

                    try {
                        const url=new URL(texto);

                        if(url.origin!==location.origin ||
                           !url.pathname.startsWith("/motor/")){
                            document.getElementById("resultado").innerText=
                                "QR Code não pertence a este ERP.";
                            return;
                        }

                        location.href=url.href;
                    } catch(e) {
                        document.getElementById("resultado").innerText=
                            "QR Code inválido.";
                    }
                }
            );
        } catch(e){
            document.getElementById("resultado").innerText=
                "Não foi possível iniciar a câmera: "+e;
        }
    }
    </script>
    """)


@app.route("/exportar")
@autenticado
def exportar():
    with conexao() as db:
        registros = db.execute(
            "SELECT * FROM motores ORDER BY tag"
        ).fetchall()

    arquivo = io.StringIO()
    writer = csv.writer(arquivo, delimiter=";")

    writer.writerow([
        "ID", "TAG", "Fabricante", "Modelo",
        "Potencia_kW", "Corrente_A", "Tensao_V",
        "Local", "Condicao", "Status",
        "Foto_ID", "Data_Cadastro"
    ])

    for m in registros:
        writer.writerow([
            m["id"],
            m["tag"],
            m["fabricante"],
            m["modelo"],
            m["potencia"],
            m["corrente"],
            m["tensao"],
            m["local"],
            m["condicao"],
            m["status"],
            m["foto"],
            m["data_cadastro"]
        ])

    dados = io.BytesIO(
        ("\ufeff" + arquivo.getvalue()).encode("utf-8")
    )

    return send_file(
        dados,
        as_attachment=True,
        download_name="inventario_motores.csv",
        mimetype="text/csv"
    )


if __name__ == "__main__":
    # Executar somente no computador durante os testes
    app.run(host="127.0.0.1", port=5000, debug=False)
