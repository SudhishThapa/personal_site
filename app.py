
# -*- coding: utf-8 -*-
import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, abort
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'site.db')  # keep the SQLite file name you're using
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-this-in-prod')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'change_me')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON;')
    return conn

def init_db():
    """Create tables if missing and seed sections when the table is empty."""
    conn = connect_db()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL
        );
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            image_path TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (section_id) REFERENCES sections(id) ON DELETE CASCADE
        );
    ''')
    existing = cur.execute('SELECT COUNT(*) AS c FROM sections').fetchone()[0]
    if existing == 0:
        sections = [
            ("Basketball", "basketball"),
            ("Music", "music"),
            ("Japanese", "japanese"),
            ("Finance", "finance"),
            ("General Learning", "general-learning"),
        ]
        cur.executemany('INSERT INTO sections(name, slug) VALUES (?, ?)', sections)
    conn.commit()
    conn.close()

def rename_section(slug: str, new_name: str):
    """Update the visible name of a section by slug (used to change 'Japanese' -> 'Japanese Studies')."""
    conn = connect_db()
    conn.execute('UPDATE sections SET name=? WHERE slug=?', (new_name, slug))
    conn.commit()
    conn.close()

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_sections():
    conn = connect_db()
    sections = conn.execute('SELECT id, name, slug FROM sections ORDER BY name').fetchall()
    conn.close()
    return sections

@app.before_first_request
def startup_tasks():
    # Ensure DB exists/seeded and apply our label change so the navbar shows "Japanese Studies"
    init_db()
    rename_section('japanese', 'Japanese Studies')

@app.route('/')
def index():
    sections = get_sections()
    conn = connect_db()
    latest_by_section = {}
    for s in sections:
        posts = conn.execute(
            'SELECT id, title, body, image_path, created_at '
            'FROM posts WHERE section_id=? '
            'ORDER BY datetime(created_at) DESC LIMIT 3',
            (s['id'],)
        ).fetchall()
        latest_by_section[s['slug']] = posts
    conn.close()
    return render_template('index.html', sections=sections, latest_by_section=latest_by_section)

@app.route('/section/<slug>')
def section(slug):
    conn = connect_db()
    sec = conn.execute('SELECT id, name, slug FROM sections WHERE slug=?', (slug,)).fetchone()
    if not sec:
        conn.close()
        abort(404)
    posts = conn.execute(
        'SELECT id, title, body, image_path, created_at '
        'FROM posts WHERE section_id=? '
        'ORDER BY datetime(created_at) DESC',
        (sec['id'],)
    ).fetchall()
    conn.close()
    return render_template('section.html', section=sec, posts=posts)

@app.route('/post/<int:post_id>')
def post_view(post_id):
    conn = connect_db()
    post = conn.execute(
        'SELECT p.id, p.title, p.body, p.image_path, p.created_at, '
        's.name as section_name, s.slug as section_slug '
        'FROM posts p JOIN sections s ON p.section_id = s.id '
        'WHERE p.id=?',
        (post_id,)
    ).fetchone()
    conn.close()
    if not post:
        abort(404)
    return render_template('post.html', post=post)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == ADMIN_PASSWORD:
            session['is_admin'] = True
            flash('Logged in successfully.', 'success')
            return redirect(url_for('admin'))
        flash('Invalid password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('is_admin', None)
    flash('Logged out.', 'info')
    return redirect(url_for('index'))

def require_admin():
    if not session.get('is_admin'):
        flash('Admin login required.', 'warning')
        return False
    return True

@app.route('/admin')
def admin():
    if not require_admin():
        return redirect(url_for('login'))
    conn = connect_db()
    posts = conn.execute(
        'SELECT p.id, p.title, p.created_at, s.name as section_name '
        'FROM posts p JOIN sections s ON p.section_id = s.id '
        'ORDER BY datetime(p.created_at) DESC'
    ).fetchall()
    conn.close()
    sections = get_sections()
    return render_template('admin.html', posts=posts, sections=sections)

@app.route('/admin/new', methods=['GET', 'POST'])
def admin_new():
    if not require_admin():
        return redirect(url_for('login'))
    sections = get_sections()
    if request.method == 'POST':
        section_id = request.form.get('section_id')
        title = request.form.get('title', '').strip()
        body = request.form.get('body', '').strip()
        image = request.files.get('image')
        image_path = None
        if image and image.filename:
            if allowed_file(image.filename):
                filename = secure_filename(image.filename)
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                if os.path.exists(save_path):
                    name, ext = os.path.splitext(filename)
                    filename = f"{name}-{int(datetime.utcnow().timestamp())}{ext}"
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                image.save(save_path)
                image_path = os.path.join('uploads', filename)
            else:
                flash('Unsupported image type.', 'danger')
                return render_template('admin_new.html', sections=sections)
        if not (section_id and title and body):
            flash('Please fill all required fields.', 'warning')
            return render_template('admin_new.html', sections=sections)
        conn = connect_db()
        conn.execute(
            'INSERT INTO posts(section_id, title, body, image_path, created_at) '
            'VALUES (?, ?, ?, ?, ?)',
            (section_id, title, body, image_path, datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()
        flash('Post created!', 'success')
        return redirect(url_for('admin'))
    return render_template('admin_new.html', sections=sections)

@app.route('/admin/edit/<int:post_id>', methods=['GET', 'POST'])
def admin_edit(post_id):
    if not require_admin():
        return redirect(url_for('login'))
    conn = connect_db()
    post = conn.execute('SELECT * FROM posts WHERE id=?', (post_id,)).fetchone()
    sections = get_sections()
    if not post:
        conn.close()
        abort(404)
    if request.method == 'POST':
        section_id = request.form.get('section_id')
        title = request.form.get('title', '').strip()
        body = request.form.get('body', '').strip()
        image = request.files.get('image')
        image_path = post['image_path']
        if image and image.filename:
            if allowed_file(image.filename):
                filename = secure_filename(image.filename)
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                if os.path.exists(save_path):
                    name, ext = os.path.splitext(filename)
                    filename = f"{name}-{int(datetime.utcnow().timestamp())}{ext}"
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                image.save(save_path)
                image_path = os.path.join('uploads', filename)
            else:
                flash('Unsupported image type.', 'danger')
                conn.close()
                return render_template('admin_edit.html', post=post, sections=sections)
        if not (section_id and title and body):
            flash('Please fill all required fields.', 'warning')
            conn.close()
            return render_template('admin_edit.html', post=post, sections=sections)
        conn.execute(
            'UPDATE posts SET section_id=?, title=?, body=?, image_path=? WHERE id=?',
            (section_id, title, body, image_path, post_id)
        )
        conn.commit()
        conn.close()
        flash('Post updated!', 'success')
        return redirect(url_for('admin'))
    conn.close()
    return render_template('admin_edit.html', post=post, sections=sections)

@app.route('/admin/delete/<int:post_id>', methods=['POST'])
def admin_delete(post_id):
    if not require_admin():
        return redirect(url_for('login'))
    conn = connect_db()
    conn.execute('DELETE FROM posts WHERE id=?', (post_id,))
    conn.commit()
    conn.close()
    flash('Post deleted.', 'info')
    return redirect(url_for('admin'))

@app.route('/static/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
