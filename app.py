
import os
import json
import sqlite3
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, send_from_directory, abort
)
from werkzeug.utils import secure_filename

# ===== Paths & Config =====
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "site.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_IMAGES_PER_POST = 15

# Create Flask app
app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

# ---- Load env vars: use .env only if present (local dev). On Render, use dashboard env vars. ----
ENV_PATH = os.path.join(BASE_DIR, ".env")
if os.path.exists(ENV_PATH):
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except Exception as e:
        print(f"Warning: could not load .env: {e}")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change_me")
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-prod")
app.config["SECRET_KEY"] = SECRET_KEY

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ===== DB Helpers =====
def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def ensure_column(conn, table, column):
    """Add a TEXT column to a SQLite table if missing."""
    cur = conn.cursor()
    cols = cur.execute(f"PRAGMA table_info({table});").fetchall()
    names = {c[1] for c in cols}
    if column not in names:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT;")
        conn.commit()


def init_db():
    conn = connect_db()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            image_path TEXT,
            image_paths TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (section_id) REFERENCES sections(id) ON DELETE CASCADE
        );
        """
    )

    # Ensure new column for multi-images (kept for backward compatibility)
    ensure_column(conn, "posts", "image_paths")

    # Seed sections if empty
    existing = cur.execute("SELECT COUNT(*) AS c FROM sections").fetchone()[0]
    if existing == 0:
        sections = [
            ("Basketball", "basketball"),
            ("Music", "music"),
            ("Japanese", "japanese"),
            ("Finance", "finance"),
            ("General Learning", "general-learning"),
        ]
        cur.executemany("INSERT INTO sections(name, slug) VALUES (?, ?)", sections)

    conn.commit()
    conn.close()


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _fix_rel_path(p: str) -> str:
    """
    Normalize stored image paths to be relative to UPLOAD_FOLDER:
    preferred: '<post_id>/<file>'
    if old data has 'uploads/<post_id>/<file>', strip leading 'uploads/'.
    """
    if not p:
        return p
    return p.split("/", 1)[1] if p.startswith("uploads/") else p


def normalize_post_row(row):
    """Convert sqlite Row to dict and parse image_paths JSON."""
    post = dict(row)

    # normalize image_paths
    raw = post.get("image_paths")
    if raw:
        try:
            imgs = json.loads(raw)
            post["image_paths"] = [_fix_rel_path(str(x)) for x in imgs if isinstance(x, str)]
        except Exception:
            post["image_paths"] = []
    else:
        post["image_paths"] = []

    # Backward compatibility for single image_path
    img1 = post.get("image_path")
    if img1:
        post["image_path"] = _fix_rel_path(img1)

    if not post.get("image_path") and post["image_paths"]:
        post["image_path"] = post["image_paths"][0]

    return post


def get_sections():
    conn = connect_db()
    sections = conn.execute("SELECT id, name, slug FROM sections ORDER BY name").fetchall()
    conn.close()
    return sections


# ===== Initialize DB at startup (Flask 3.x & Gunicorn safe) =====
try:
    with app.app_context():
        init_db()
except Exception as e:
    print(f"DB init failed: {e}")


# ===== Routes =====
@app.route("/")
def index():
    sections = get_sections()
    conn = connect_db()
    latest_by_section = {}
    for s in sections:
        rows = conn.execute(
            """
            SELECT id, title, body, image_path, image_paths, created_at
            FROM posts
            WHERE section_id=?
            ORDER BY datetime(created_at) DESC
            LIMIT 3
            """,
            (s["id"],),
        ).fetchall()
        latest_by_section[s["slug"]] = [normalize_post_row(r) for r in rows]
    conn.close()
    return render_template("index.html", sections=sections, latest_by_section=latest_by_section)


@app.route("/section/<slug>")
def section(slug):
    conn = connect_db()
    sec = conn.execute("SELECT id, name, slug FROM sections WHERE slug=?", (slug,)).fetchone()
    if not sec:
        conn.close()
        abort(404)
    rows = conn.execute(
        """
        SELECT id, title, body, image_path, image_paths, created_at
        FROM posts
        WHERE section_id=?
        ORDER BY datetime(created_at) DESC
        """,
        (sec["id"],),
    ).fetchall()
    posts = [normalize_post_row(r) for r in rows]
    conn.close()
    return render_template("section.html", section=sec, posts=posts)


@app.route("/post/<int:post_id>")
def post_view(post_id):
    conn = connect_db()
    row = conn.execute(
        """
        SELECT p.id, p.title, p.body, p.image_path, p.image_paths, p.created_at,
               s.name as section_name, s.slug as section_slug
        FROM posts p
        JOIN sections s ON p.section_id = s.id
        WHERE p.id=?
        """,
        (post_id,),
    ).fetchone()
    conn.close()
    if not row:
        abort(404)
    post = normalize_post_row(row)
    return render_template("post.html", post=post)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session["is_admin"] = True
            flash("Logged in successfully.", "success")
            return redirect(url_for("admin"))
        flash("Invalid password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("is_admin", None)
    flash("Logged out.", "info")
    return redirect(url_for("index"))


def require_admin():
    if not session.get("is_admin"):
        flash("Admin login required.", "warning")
        return False
    return True


@app.route("/admin")
def admin():
    if not require_admin():
        return redirect(url_for("login"))
    conn = connect_db()
    posts = conn.execute(
        """
        SELECT p.id, p.title, p.created_at, s.name as section_name
        FROM posts p
        JOIN sections s ON p.section_id = s.id
        ORDER BY datetime(p.created_at) DESC
        """
    ).fetchall()
    conn.close()
    sections = get_sections()
    return render_template("admin.html", posts=posts, sections=sections)


# ===== Create New Post (supports multiple images) =====
@app.route("/admin/new", methods=["GET", "POST"])
def admin_new():
    if not require_admin():
        return redirect(url_for("login"))

    sections = get_sections()

    if request.method == "POST":
        section_id = request.form.get("section_id")
        title = request.form.get("title", "").strip()
        body = request.form.get("body", "").strip()

        if not (section_id and title and body):
            flash("Please fill all required fields.", "warning")
            return render_template("admin_new.html", sections=sections)

        # 1) Create the post first to get post_id
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO posts (section_id, title, body, image_path, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (section_id, title, body, None, datetime.utcnow().isoformat()),
        )
        post_id = cur.lastrowid

        # 2) Save multiple images
        files = request.files.getlist("images")
        legacy_single = request.files.get("image")
        if legacy_single and legacy_single.filename:
            files.append(legacy_single)

        dest_dir = os.path.join(app.config["UPLOAD_FOLDER"], str(post_id))
        os.makedirs(dest_dir, exist_ok=True)

        image_paths = []
        for f in files:
            if not f or f.filename == "":
                continue
            if len(image_paths) >= MAX_IMAGES_PER_POST:
                flash(f"Max {MAX_IMAGES_PER_POST} images per post. Extra files ignored.", "warning")
                break
            if not allowed_file(f.filename):
                flash(f"Unsupported image type: {f.filename}", "danger")
                continue

            filename = secure_filename(f.filename)
            name, ext = os.path.splitext(filename)

            final = filename
            i = 1
            while os.path.exists(os.path.join(dest_dir, final)):
                final = f"{name}-{i}{ext}"
                i += 1

            save_path = os.path.join(dest_dir, final)
            f.save(save_path)

            # Store path relative to /static/uploads: '<post_id>/<final>'
            rel_path = os.path.join(str(post_id), final).replace("\\", "/")
            image_paths.append(rel_path)

        first_image = image_paths[0] if image_paths else None
        cur.execute(
            "UPDATE posts SET image_path=?, image_paths=? WHERE id=?",
            (first_image, json.dumps(image_paths), post_id),
        )
        conn.commit()
        conn.close()

        flash("Post created!", "success")
        return redirect(url_for("admin"))

    return render_template("admin_new.html", sections=sections)


# ===== Edit Post (optional: append more images) =====
@app.route("/admin/edit/<int:post_id>", methods=["GET", "POST"])
def admin_edit(post_id):
    if not require_admin():
        return redirect(url_for("login"))

    conn = connect_db()
    post_row = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    sections = get_sections()
    if not post_row:
        conn.close()
        abort(404)

    if request.method == "POST":
        section_id = request.form.get("section_id")
        title = request.form.get("title", "").strip()
        body = request.form.get("body", "").strip()

        existing_raw = post_row["image_paths"]
        try:
            existing_list = json.loads(existing_raw) if existing_raw else []
        except Exception:
            existing_list = []

        # Normalize any old 'uploads/<post_id>/file' entries
        existing_list = [_fix_rel_path(x) for x in existing_list if isinstance(x, str)]

        files = request.files.getlist("images")
        legacy_single = request.files.get("image")
        if legacy_single and legacy_single.filename:
            files.append(legacy_single)

        dest_dir = os.path.join(app.config["UPLOAD_FOLDER"], str(post_id))
        os.makedirs(dest_dir, exist_ok=True)

        for f in files:
            if not f or f.filename == "":
                continue
            if len(existing_list) >= MAX_IMAGES_PER_POST:
                flash(f"Max {MAX_IMAGES_PER_POST} images per post. Extra files ignored.", "warning")
                break
            if not allowed_file(f.filename):
                flash(f"Unsupported image type: {f.filename}", "danger")
                continue

            filename = secure_filename(f.filename)
            name, ext = os.path.splitext(filename)
            final = filename
            i = 1
            while os.path.exists(os.path.join(dest_dir, final)):
                final = f"{name}-{i}{ext}"
                i += 1

            save_path = os.path.join(dest_dir, final)
            f.save(save_path)
            rel_path = os.path.join(str(post_id), final).replace("\\", "/")
            existing_list.append(rel_path)

        first_image = existing_list[0] if existing_list else None

        if not (section_id and title and body):
            flash("Please fill all required fields.", "warning")
            conn.close()
            return render_template("admin_edit.html", post=post_row, sections=sections)

        conn.execute(
            """
            UPDATE posts
            SET section_id=?, title=?, body=?, image_path=?, image_paths=?
            WHERE id=?
            """,
            (section_id, title, body, first_image, json.dumps(existing_list), post_id),
        )
        conn.commit()
        conn.close()

        flash("Post updated!", "success")
        return redirect(url_for("admin"))

    conn.close()
    return render_template("admin_edit.html", post=post_row, sections=sections)


@app.route("/admin/delete/<int:post_id>", methods=["POST"])
def admin_delete(post_id):
    if not require_admin():
        return redirect(url_for("login"))
    conn = connect_db()
    conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
    conn.commit()
    conn.close()
    flash("Post deleted.", "info")
    return redirect(url_for("admin"))


# Serve files saved under static/uploads/<post_id>/...
@app.route("/static/uploads/<path:filename>")
def uploaded_file(filename):
    # filename should be '<post_id>/<file>'
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# Local dev entrypoint (Render uses Gunicorn via Procfile)
if __name__ == "__main__":
    # For local dev (safe to call; CREATE TABLE IF NOT EXISTS is idempotent)
    init_db()
    app.run(debug=True, host="127.0.0.1", port=5000)