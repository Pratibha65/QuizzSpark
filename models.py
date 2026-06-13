# models.py
from flask_sqlalchemy import SQLAlchemy

# Initialize the db object here -> not linked to app here
db = SQLAlchemy()

# Define your tables
class Challenge(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    topic = db.Column(db.String(100))
    difficulty = db.Column(db.String(50))
    quiz_data = db.Column(db.Text)    # Stores the questions & options
    answers_data = db.Column(db.Text) # Stores the correct answers