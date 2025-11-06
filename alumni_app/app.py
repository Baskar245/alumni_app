from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, g
)
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "app.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = "replace_this_with_a_random_secret"  # change in production
app.config["DATABASE"] = DB_PATH

# -------------------------
# Database helpers
# -------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(app.config["DATABASE"])
    c = db.cursor()
    # admin table
    c.execute('''
    CREATE TABLE IF NOT EXISTS admin (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )
    ''')
    # alumni table (includes current students if you want to store them)
    c.execute('''
    CREATE TABLE IF NOT EXISTS alumni (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        reg_no TEXT UNIQUE NOT NULL,
        dob TEXT NOT NULL,
        email TEXT,
        batch_year INTEGER,
        department TEXT
    )
    ''')
    # jobs table
    c.execute('''
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        company TEXT,
        description TEXT,
        link TEXT,
        posted_by TEXT,
        date_posted TEXT
    )
    ''')
    db.commit()

    # create default admin if not exists
    c.execute("SELECT * FROM admin WHERE username = ?", ("admin",))
    if not c.fetchone():
        default_pw = generate_password_hash("admin123")
        c.execute("INSERT INTO admin (username, password) VALUES (?, ?)", ("admin", default_pw))
        db.commit()
    db.close()

# init DB on first run
if not os.path.exists(app.config["DATABASE"]):
    init_db()

# -------------------------
# Routes - Public
# -------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/view-jobs")
def view_jobs():
    db = get_db()
    cur = db.execute("SELECT * FROM jobs ORDER BY date_posted DESC")
    jobs = cur.fetchall()
    return render_template("view_jobs.html", jobs=jobs)

# -------------------------
# Admin routes
# -------------------------
@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        db = get_db()
        cur = db.execute("SELECT * FROM admin WHERE username = ?", (username,))
        admin = cur.fetchone()
        if admin and check_password_hash(admin["password"], password):
            session["admin_logged_in"] = True
            session["admin_username"] = username
            flash("Admin logged in", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid admin credentials", "danger")
    return render_template("admin_login.html")

def admin_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("Please login as admin", "warning")
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/admin-dashboard")
@admin_required
def admin_dashboard():
    db = get_db()
    cur = db.execute("SELECT * FROM alumni ORDER BY batch_year DESC, name ASC")
    alumni = cur.fetchall()
    # show jobs too
    cur = db.execute("SELECT * FROM jobs ORDER BY date_posted DESC")
    jobs = cur.fetchall()
    return render_template("admin_dashboard.html", alumni=alumni, jobs=jobs)

@app.route("/add-alumni", methods=["GET", "POST"])
@admin_required
def add_alumni():
    if request.method == "POST":
        name = request.form["name"].strip()
        reg_no = request.form["reg_no"].strip()
        dob = request.form["dob"].strip()  # expect YYYY-MM-DD
        email = request.form.get("email", "").strip()
        batch_year = request.form.get("batch_year")
        department = request.form.get("department", "").strip()
        db = get_db()
        try:
            db.execute(
                "INSERT INTO alumni (name, reg_no, dob, email, batch_year, department) VALUES (?, ?, ?, ?, ?, ?)",
                (name, reg_no, dob, email, batch_year, department)
            )
            db.commit()
            flash("Alumni/student added", "success")
            return redirect(url_for("admin_dashboard"))
        except sqlite3.IntegrityError:
            flash("Registration number already exists", "danger")
    return render_template("add_alumni.html")

@app.route("/edit-alumni/<int:al_id>", methods=["GET", "POST"])
@admin_required
def edit_alumni(al_id):
    db = get_db()
    cur = db.execute("SELECT * FROM alumni WHERE id = ?", (al_id,))
    rec = cur.fetchone()
    if not rec:
        flash("Record not found", "danger")
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        name = request.form["name"].strip()
        reg_no = request.form["reg_no"].strip()
        dob = request.form["dob"].strip()
        email = request.form.get("email", "").strip()
        batch_year = request.form.get("batch_year")
        department = request.form.get("department", "").strip()
        try:
            db.execute(
                "UPDATE alumni SET name=?, reg_no=?, dob=?, email=?, batch_year=?, department=? WHERE id = ?",
                (name, reg_no, dob, email, batch_year, department, al_id)
            )
            db.commit()
            flash("Record updated", "success")
            return redirect(url_for("admin_dashboard"))
        except sqlite3.IntegrityError:
            flash("Registration number conflict", "danger")
    return render_template("edit_alumni.html", rec=rec)

@app.route("/delete-alumni/<int:al_id>", methods=["POST"])
@admin_required
def delete_alumni(al_id):
    db = get_db()
    db.execute("DELETE FROM alumni WHERE id = ?", (al_id,))
    db.commit()
    flash("Record deleted", "info")
    return redirect(url_for("admin_dashboard"))

# -------------------------
# Alumni (pass-out) login & dashboard
# -------------------------
@app.route("/user-login", methods=["GET", "POST"])
def user_login():
    if request.method == "POST":
        reg_no = request.form["reg_no"].strip()
        dob = request.form["dob"].strip()  # expect YYYY-MM-DD
        db = get_db()
        cur = db.execute("SELECT * FROM alumni WHERE reg_no = ? AND dob = ?", (reg_no, dob))
        user = cur.fetchone()
        if user:
            session["user_logged_in"] = True
            session["user_reg_no"] = reg_no
            session["user_name"] = user["name"]
            flash("Logged in as " + user["name"], "success")
            return redirect(url_for("alumni_dashboard"))
        else:
            flash("Invalid register number or DOB", "danger")
    return render_template("user_login.html")

def user_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_logged_in"):
            flash("Please login as alumni to continue", "warning")
            return redirect(url_for("user_login"))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/alumni-dashboard", methods=["GET", "POST"])
@user_required
def alumni_dashboard():
    db = get_db()
    if request.method == "POST":
        title = request.form["title"].strip()
        company = request.form.get("company", "").strip()
        description = request.form.get("description", "").strip()
        link = request.form.get("link", "").strip()
        posted_by = f"{session.get('user_name')} ({session.get('user_reg_no')})"
        date_posted = datetime.utcnow().isoformat()
        db.execute(
            "INSERT INTO jobs (title, company, description, link, posted_by, date_posted) VALUES (?, ?, ?, ?, ?, ?)",
            (title, company, description, link, posted_by, date_posted)
        )
        db.commit()
        flash("Job/internship posted", "success")
        return redirect(url_for("alumni_dashboard"))
    cur = db.execute("SELECT * FROM jobs ORDER BY date_posted DESC")
    jobs = cur.fetchall()
    return render_template("alumni_dashboard.html", jobs=jobs)

# -------------------------
# Logout
# -------------------------
@app.route("/logout")
def logout():
    session_keys = ["admin_logged_in", "admin_username", "user_logged_in", "user_reg_no", "user_name"]
    for k in session_keys:
        session.pop(k, None)
    flash("Logged out", "info")
    return redirect(url_for("index"))

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    app.run(debug=True)
