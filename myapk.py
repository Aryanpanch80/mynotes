from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, FileField, BooleanField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Length, EqualTo
from sqlalchemy import or_, and_, text
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os

app = Flask(__name__, template_folder="templates")
app.config['SECRET_KEY'] = 'your-secret-key-here-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///notes.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config["UPLOAD_FOLDER"] = "uploads"

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    notes = db.relationship('Note', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(200), nullable=False)
    semester = db.Column(db.String(100), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_global = db.Column(db.Boolean, default=False)
    category = db.Column(db.String(50), default='General')
    ratings = db.relationship('Rating', backref='note', lazy=True, cascade='all, delete-orphan')

class Rating(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    note_id = db.Column(db.Integer, db.ForeignKey('note.id', ondelete='CASCADE'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5 stars
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    # Ensure one rating per user per note
    __table_args__ = (db.UniqueConstraint('user_id', 'note_id', name='unique_user_note_rating'),)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=150)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class UploadForm(FlaskForm):
    subject = StringField('Subject', validators=[DataRequired()])
    semester = StringField('Semester', validators=[DataRequired()])
    category = SelectField('Category', choices=[('Coding', 'Coding'), ('General', 'General'), ('Other', 'Other')], default='General')
    file = FileField('File', validators=[DataRequired()])
    is_global = BooleanField('Share globally (all users can see)', default=False)
    submit = SubmitField('Upload')

@app.route("/")
@login_required
def index():
    query = request.args.get("q")
    category = request.args.get("category", "All")
    base_filter = or_(Note.user_id == current_user.id, Note.is_global == True)
    
    if category != "All":
        base_filter = and_(base_filter, Note.category == category)
    
    if query:
        notes = Note.query.filter(base_filter, Note.subject.contains(query)).all()
    else:
        notes = Note.query.filter(base_filter).all()
    
    # Get ratings data for each note
    notes_with_ratings = []
    for note in notes:
        # Calculate average rating
        ratings = [r.rating for r in note.ratings]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0
        
        # Check if current user has rated this note
        user_rating = Rating.query.filter_by(user_id=current_user.id, note_id=note.id).first()
        user_rating_value = user_rating.rating if user_rating else 0
        
        notes_with_ratings.append({
            'note': note,
            'avg_rating': avg_rating,
            'rating_count': len(ratings),
            'user_rating': user_rating_value
        })
    
    return render_template("index.html", notes_data=notes_with_ratings, current_category=category)

@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    form = UploadForm()
    if form.validate_on_submit():
        file = form.file.data
        if file:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)

            note = Note(
                subject=form.subject.data,
                semester=form.semester.data,
                filename=filename,
                user_id=current_user.id,
                is_global=form.is_global.data,
                category=form.category.data
            )
            db.session.add(note)
            db.session.commit()

            flash('Notes uploaded successfully!', 'success')
            return redirect(url_for("index"))

    return render_template("upload.html", form=form)

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user:
            flash('Username already exists. Please choose a different one.', 'error')
            return redirect(url_for('register'))
        user = User(username=form.username.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template("register.html", form=form)

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid username or password', 'error')
    return render_template("login.html", form=form)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route("/view/<filename>")
@login_required
def view_file(filename):
    # Check if the file belongs to the current user or is global
    note = Note.query.filter_by(filename=filename).filter(or_(Note.user_id == current_user.id, Note.is_global == True)).first()
    if not note:
        flash('File not found or access denied.', 'error')
        return redirect(url_for('index'))

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    if not os.path.exists(filepath):
        flash('File not found on server.', 'error')
        return redirect(url_for('index'))

    # Get rating data
    ratings = [r.rating for r in note.ratings]
    avg_rating = sum(ratings) / len(ratings) if ratings else 0
    user_rating = Rating.query.filter_by(user_id=current_user.id, note_id=note.id).first()
    user_rating_value = user_rating.rating if user_rating else 0

    # Check if it's a text file
    if filename.lower().endswith('.txt'):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            return render_template('view_file.html', content=content, filename=filename, note=note, 
                                 avg_rating=avg_rating, rating_count=len(ratings), user_rating=user_rating_value)
        except UnicodeDecodeError:
            # If not UTF-8, redirect to download
            return redirect(url_for('download_file', filename=filename))

    # For non-text files, redirect to download
    return redirect(url_for('download_file', filename=filename))

@app.route("/download/<filename>")
@login_required
def download_file(filename):
    # Check if the file belongs to the current user or is global
    note = Note.query.filter_by(filename=filename).filter(or_(Note.user_id == current_user.id, Note.is_global == True)).first()
    if not note:
        flash('File not found or access denied.', 'error')
        return redirect(url_for('index'))

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    if not os.path.exists(filepath):
        flash('File not found on server.', 'error')
        return redirect(url_for('index'))

    return send_file(filepath, as_attachment=True, download_name=filename)

@app.route("/rate/<int:note_id>", methods=["POST"])
@login_required
def rate_note(note_id):
    note = Note.query.get_or_404(note_id)
    
    # Check if user can access this note
    if note.user_id != current_user.id and not note.is_global:
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    
    rating_value = request.form.get('rating', type=int)
    if not rating_value or rating_value < 1 or rating_value > 5:
        flash('Invalid rating value.', 'error')
        return redirect(url_for('index'))
    
    # Check if user already rated this note
    existing_rating = Rating.query.filter_by(user_id=current_user.id, note_id=note_id).first()
    
    if existing_rating:
        existing_rating.rating = rating_value
        flash('Rating updated successfully!', 'success')
    else:
        new_rating = Rating(user_id=current_user.id, note_id=note_id, rating=rating_value)
        db.session.add(new_rating)
        flash('Rating submitted successfully!', 'success')
    
    db.session.commit()
    return redirect(url_for('index'))

@app.route("/delete/<int:note_id>", methods=["POST"])
@login_required
def delete_note(note_id):
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('index'))

    note = Note.query.get_or_404(note_id)

    # Remove the file from filesystem
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], note.filename)
    if os.path.exists(filepath):
        os.remove(filepath)

    # Remove related ratings (safe if cascade is not yet active on existing database)
    Rating.query.filter_by(note_id=note_id).delete()

    # Remove the note
    db.session.delete(note)
    db.session.commit()

    flash('Note deleted successfully.', 'success')
    return redirect(url_for('admin_panel'))

@app.route("/promote/<int:user_id>", methods=["POST"])
@login_required
def promote_user(user_id):
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('index'))

    user = User.query.get_or_404(user_id)

    if user.is_admin:
        flash(f'User {user.username} is already an admin.', 'error')
    else:
        user.is_admin = True
        db.session.commit()
        flash(f'User {user.username} has been promoted to admin.', 'success')

    return redirect(url_for('admin_panel'))

@app.route("/demote/<int:user_id>", methods=["POST"])
@login_required
def demote_user(user_id):
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('index'))

    user = User.query.get_or_404(user_id)

    # Prevent demoting yourself
    if user.id == current_user.id:
        flash('You cannot demote yourself.', 'error')
        return redirect(url_for('admin_panel'))

    if not user.is_admin:
        flash(f'User {user.username} is not an admin.', 'error')
    else:
        user.is_admin = False
        db.session.commit()
        flash(f'User {user.username} has been demoted from admin.', 'success')

    return redirect(url_for('admin_panel'))

@app.route("/admin")
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('index'))

    users = User.query.all()
    notes = Note.query.all()
    return render_template('admin.html', users=users, notes=notes)

if __name__ == "__main__":
    os.makedirs("uploads", exist_ok=True)
    with app.app_context():
        db.create_all()

        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('note')] if inspector.has_table('note') else []
        if 'is_global' not in columns:
            try:
                with db.engine.connect() as conn:
                    conn.execute(text('ALTER TABLE note ADD COLUMN is_global BOOLEAN DEFAULT 0'))
                    conn.commit()
                print('Migration: note.is_global column added.')
            except Exception as e:
                print('Migration error (can ignore if already successful):', e)
        
        if 'category' not in columns:
            try:
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE note ADD COLUMN category VARCHAR(50) DEFAULT 'General'"))
                    conn.commit()
                print('Migration: note.category column added.')
            except Exception as e:
                print('Migration error (can ignore if already successful):', e)

        # Make the first user an admin if no admins exist
        if not User.query.filter_by(is_admin=True).first():
            first_user = User.query.first()
            if first_user:
                first_user.is_admin = True
                db.session.commit()
                print(f"Made user '{first_user.username}' an admin.")
    app.run(debug=True)

