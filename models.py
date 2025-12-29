
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# Topic slugs used in URLs and DB
TOPICS = ["basketball", "music", "japanese-studies", "finance", "general-learning"]

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(180), unique=True, nullable=False)
    topic = db.Column(db.String(40), nullable=False)  # slug, e.g., 'japanese-studies'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    media = db.relationship("Media", backref="post", cascade="all, delete-orphan")

class Media(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    url = db.Column(db.String(400), nullable=False)   # /static/uploads/... or S3 URL
    kind = db.Column(db.String(10), nullable=False)   # 'image' or 'video'
