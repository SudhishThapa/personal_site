
import os, re, uuid
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, abort, session
)
from werkzeug.utils import secure_filename
from config import Config
from models import db, Post, Media, TOPICS

# Register Flask-Migrate
from flask_migrate import Migrate
migrate = Migrate()

# Pretty display names for navbar and headings
DISPLAY_NAMES = {
    "basketball": "Basketball",
    "music": "Music",
    "japanese-studies": "Japanese Studies",
    "finance": "Finance",
    "general-learning": "General Learning",
}

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    # Session hardening
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Ensure folders exist
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # DB + Migrations init
    db.init_app(app)
    migrate.init_app(app, db)  # enables `flask db ...` CLI

    # Inject globals to all templates
    @app.context_processor
    def inject_globals():
        return dict(topics=TOPICS, display_names=DISPLAY_NAMES, session=session)

    # Helpers
    def slugify(text):
        text = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
        text = re.sub(r"[\s-]+", "-", text)
        return text or str(uuid.uuid4())

    def allowed(filename, allow):
        return "." in filename and filename.rsplit(".", 1)[1].lower() in allow

    def save_file(fs):
        """Save locally to static/uploads and return (url, kind)."""
        if not fs or fs.filename == "":
            raise ValueError("Empty file.")
        filename = secure_filename(fs.filename)
        ext = filename.rsplit(".", 1)[1].lower()

        if allowed(filename, app.config["ALLOWED_IMAGE_EXTENSIONS"]):
            kind = "image"
        elif allowed(filename, app.config["ALLOWED_VIDEO_EXTENSIONS"]):
            kind = "video"
        else:
            raise ValueError("Unsupported file type.")

        unique = f"{uuid.uuid4().hex}.{ext}"
        path = os.path.join(app.config["UPLOAD_FOLDER"], unique)
        fs.save(path)
        url = "/" + path.replace("\\", "/")
        return url, kind

    def is_logged_in():
        return session.get("is_admin") is True

    # Routes
    @app.route("/")
    def index():
        posts = Post.query.order_by(Post.created_at.desc()).limit(30).all()
        return render_template("index.html", posts=posts)

    @app.route("/topic/<topic>")
    def topic(topic):
        if topic not in TOPICS:
            abort(404)
        posts = Post.query.filter_by(topic=topic).order_by(Post.created_at.desc()).all()
        return render_template("topic.html", posts=posts, topic=topic)

    @app.route("/post/<slug>")
    def post_detail(slug):
        post = Post.query.filter_by(slug=slug).first_or_404()
        return render_template("post_detail.html", post=post)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if request.form.get("password") == app.config["ADMIN_PASSWORD"]:
                session["is_admin"] = True
                flash("Logged in.", "success")
                return redirect(url_for("index"))
            flash("Invalid password.", "danger")
            return redirect(url_for("login"))
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.pop("is_admin", None)
        flash("Logged out.", "info")
        return redirect(url_for("index"))

    @app.route("/admin/new", methods=["GET", "POST"])
    def admin_new_post():
        admin_password = app.config["ADMIN_PASSWORD"]
        if not admin_password:
            return "ADMIN_PASSWORD not configured in .env", 500

        if not is_logged_in():
            return redirect(url_for("login"))

        if request.method == "POST":
            title = request.form.get("title", "").strip()
            topic = request.form.get("topic", "").strip()
            content = request.form.get("content", "").strip()
            if not title or topic not in TOPICS or not content:
                flash("Please complete all fields.", "warning")
                return redirect(request.url)

            base_slug = slugify(title)
            slug = base_slug
            i = 1
            while Post.query.filter_by(slug=slug).first():
                i += 1
                slug = f"{base_slug}-{i}"

            post = Post(title=title, slug=slug, topic=topic, content=content)
            db.session.add(post)
            db.session.commit()

            files = request.files.getlist("media")
            saved = 0
            for f in files:
                if not f or f.filename == "":
                    continue
                try:
                    url, kind = save_file(f)
                    db.session.add(Media(post_id=post.id, url=url, kind=kind))
                    saved += 1
                except Exception as e:
                    flash(f"Skipped {f.filename}: {e}", "warning")

            db.session.commit()
            flash(f"Post created! {saved} media file(s) uploaded.", "success")
            return redirect(url_for("post_detail", slug=post.slug))

        return render_template("admin_new_post.html")

    # ---------- Edit Post ----------
    @app.route("/admin/edit/<int:post_id>", methods=["GET", "POST"])
    def admin_edit_post(post_id):
        if not is_logged_in():
            return redirect(url_for("login"))

        post = Post.query.get_or_404(post_id)

        if request.method == "POST":
            title = request.form.get("title", "").strip()
            topic = request.form.get("topic", "").strip()
            content = request.form.get("content", "").strip()
            update_slug = request.form.get("update_slug") == "on"

            if not title or topic not in TOPICS or not content:
                flash("Please complete all fields.", "warning")
                return redirect(request.url)

            post.title = title
            post.topic = topic
            post.content = content

            # Optional: update slug to match new title
            if update_slug:
                base_slug = slugify(title)
                slug = base_slug
                i = 1
                # Ensure uniqueness excluding current post
                while Post.query.filter(Post.slug == slug, Post.id != post.id).first():
                    i += 1
                    slug = f"{base_slug}-{i}"
                post.slug = slug

            # Handle media deletions (checkboxes)
            delete_ids = request.form.getlist("delete_media_ids")
            for mid in delete_ids:
                try:
                    m = Media.query.filter_by(id=int(mid), post_id=post.id).first()
                except ValueError:
                    m = None
                if m:
                    db.session.delete(m)

            # Handle new uploads (append)
            files = request.files.getlist("media")
            added = 0
            for f in files:
                if not f or f.filename == "":
                    continue
                try:
                    url, kind = save_file(f)
                    db.session.add(Media(post_id=post.id, url=url, kind=kind))
                    added += 1
                except Exception as e:
                    flash(f"Skipped {f.filename}: {e}", "warning")

            db.session.commit()
            flash(f"Post updated. {len(delete_ids)} removed, {added} added.", "success")
            return redirect(url_for("post_detail", slug=post.slug))

        return render_template("admin_edit_post.html", post=post)

    # ---------- Delete Post ----------
    @app.route("/admin/delete/<int:post_id>", methods=["POST"])
    def admin_delete_post(post_id):
        if not is_logged_in():
            return redirect(url_for("login"))

        post = Post.query.get_or_404(post_id)
        db.session.delete(post)  # media will be deleted via cascade
        db.session.commit()
        flash("Post deleted.", "info")
        return redirect(url_for("index"))

    return app

# Optional: keep a global app for `python app.py` local runs
app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
