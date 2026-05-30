from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import os
import sqlite3
import time
import pdfplumber
from groq import Groq
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "secondbrainai2026"

UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {"pdf", "txt", "docx"}

client = Groq(api_key="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")

def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def load_texts_from_db(user_id):
    conn = get_db()
    files = conn.execute(
        "SELECT filename, content FROM files WHERE user_id=?",
        (user_id,)
    ).fetchall()
    conn.close()
    texts = {}
    for file in files:
        texts[file['filename']] = file['content']
    return texts

def allowed_file(filename):
    return "." in filename and \
           filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text(filepath, filename):
    text = ""
    if filename.endswith(".pdf"):
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
    elif filename.endswith(".txt"):
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()
    elif filename.endswith(".docx"):
        from docx import Document
        doc = Document(filepath)
        for para in doc.paragraphs:
            text += para.text + "\n"
    return text

def is_logged_in():
    return 'user_id' in session

@app.route("/")
def home():
    if is_logged_in():
        return redirect(url_for('dashboard'))
    return render_template("login.html")

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    name = data.get("name", "")
    email = data.get("email", "")
    password = data.get("password", "")
    if not name or not email or not password:
        return jsonify({"error": "All fields required"}), 400
    hashed = generate_password_hash(password)
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO users (name, email, password) VALUES (?,?,?)",
            (name, email, hashed)
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "Account created! ✅"})
    except:
        return jsonify({"error": "Email already exists!"}), 400

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email", "")
    password = data.get("password", "")
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE email=?",
        (email,)
    ).fetchone()
    conn.close()
    if user and check_password_hash(user['password'], password):
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        return jsonify({"message": "Login successful! ✅"})
    else:
        return jsonify({"error": "Wrong email or password!"}), 401

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route("/dashboard")
def dashboard():
    if not is_logged_in():
        return redirect(url_for('home'))
    return render_template("dashboard.html",
                           user_name=session.get('user_name'))

@app.route("/upload")
def upload():
    if not is_logged_in():
        return redirect(url_for('home'))
    return render_template("upload.html")

@app.route("/chat")
def chat():
    if not is_logged_in():
        return redirect(url_for('home'))
    return render_template("chat.html")

@app.route("/upload-file", methods=["POST"])
def upload_file():
    if not is_logged_in():
        return jsonify({"error": "Please login first"}), 401
    if "file" not in request.files:
        return jsonify({"error": "No file found"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
    if file and allowed_file(file.filename):
        filepath = os.path.join(app.config["UPLOAD_FOLDER"],
                                file.filename)
        file.save(filepath)
        text = extract_text(filepath, file.filename)
        conn = get_db()
        existing = conn.execute(
            "SELECT id FROM files WHERE filename=? AND user_id=?",
            (file.filename, session['user_id'])
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE files SET content=? WHERE filename=? AND user_id=?",
                (text, file.filename, session['user_id'])
            )
        else:
            conn.execute(
                "INSERT INTO files (filename, content, user_id) VALUES (?,?,?)",
                (file.filename, text, session['user_id'])
            )
        conn.commit()
        conn.close()
        preview = text[:300] if text else "No text found"
        return jsonify({
            "message": f"{file.filename} saved! ✅",
            "preview": preview,
            "total_characters": len(text)
        })
    return jsonify({"error": "File type not allowed"}), 400

@app.route("/ask", methods=["POST"])
def ask():
    if not is_logged_in():
        return jsonify({"error": "Please login first"}), 401
    try:
        data = request.json
        question = data.get("question", "")
        if not question:
            return jsonify({"error": "No question"}), 400
        texts = load_texts_from_db(session['user_id'])
        all_text = "\n\n".join(texts.values())
        if not all_text:
            return jsonify({
                "answer": "Please upload notes first! 📚"
            })
        prompt = f"""You are a helpful study assistant.

Follow these rules:
1. If answer is in notes — answer FROM notes
2. If answer is NOT in notes — answer from 
   your general AI knowledge
3. Always say which source you used like:
   "From your notes: ..." or 
   "From general knowledge: ..."

NOTES:
{all_text[:6000]}

QUESTION: {question}

Give a clear helpful answer."""

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}]
        )
        answer = response.choices[0].message.content
        conn = get_db()
        conn.execute(
            "INSERT INTO chats (question, answer) VALUES (?,?)",
            (question, answer)
        )
        conn.commit()
        conn.close()
        return jsonify({"answer": answer})
    except Exception as e:
        print("ERROR:", str(e))
        return jsonify({"answer": f"Error: {str(e)}"})

@app.route("/files", methods=["GET"])
def get_files():
    if not is_logged_in():
        return jsonify([])
    conn = get_db()
    files = conn.execute(
        "SELECT filename, uploaded_at FROM files WHERE user_id=?",
        (session['user_id'],)
    ).fetchall()
    conn.close()
    return jsonify([dict(f) for f in files])

if __name__ == "__main__":
    app.run(debug=True)