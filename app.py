import os
import sqlite3
import uuid
from datetime import datetime
from functools import wraps

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

ALLOWED_EXTENSIONS = {
    "pdf", "txt", "doc", "docx", "xls", "xlsx",
    "ppt", "pptx", "csv",
    "jpg", "jpeg", "png", "gif",
    "zip"
}

if not S3_BUCKET_NAME:
    raise RuntimeError("S3_BUCKET_NAME is missing in .env")

# boto3 automatically reads AWS credentials from environment variables.
s3 = boto3.client("s3", region_name=AWS_REGION)

DB_NAME = "database.db"


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            original_name TEXT NOT NULL,
            s3_key TEXT UNIQUE NOT NULL,
            content_type TEXT,
            size INTEGER NOT NULL,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def get_owned_file(file_id):
    conn = get_db()
    file_row = conn.execute(
        "SELECT * FROM files WHERE id = ? AND user_id = ?",
        (file_id, session["user_id"])
    ).fetchone()
    conn.close()

    if file_row is None:
        abort(404)
    return file_row


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("All fields are required.", "danger")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "danger")
            return render_template("register.html")

        password_hash = generate_password_hash(password)

        conn = get_db()
        try:
            conn.execute(
                """
                INSERT INTO users (name, email, password, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (name, email, password_hash, datetime.now().isoformat())
            )
            conn.commit()
        except sqlite3.IntegrityError:
            flash("An account with this email already exists.", "danger")
            conn.close()
            return render_template("register.html")
        conn.close()

        flash("Registration successful. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()

    files = conn.execute(
        """
        SELECT * FROM files
        WHERE user_id = ?
        ORDER BY uploaded_at DESC
        """,
        (session["user_id"],)
    ).fetchall()

    total_files = len(files)
    total_size = sum(row["size"] for row in files)
    conn.close()

    return render_template(
        "dashboard.html",
        files=files,
        total_files=total_files,
        total_size=total_size
    )


@app.route("/upload", methods=["POST"])
@login_required
def upload():
    file = request.files.get("file")

    if not file or file.filename == "":
        flash("Please select a file.", "danger")
        return redirect(url_for("dashboard"))

    if not allowed_file(file.filename):
        flash(
            "File type not allowed. Allowed: PDF, documents, spreadsheets, "
            "images, CSV, ZIP and text files.",
            "danger"
        )
        return redirect(url_for("dashboard"))

    original_name = secure_filename(file.filename)

    if not original_name:
        flash("Invalid filename.", "danger")
        return redirect(url_for("dashboard"))

    # Generate a unique S3 object key and keep each user's files separated.
    s3_key = f"user_{session['user_id']}/{uuid.uuid4().hex}_{original_name}"

    try:
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)

        if file_size == 0:
            flash("Empty files are not allowed.", "danger")
            return redirect(url_for("dashboard"))

        if file_size > app.config["MAX_CONTENT_LENGTH"]:
            flash("Maximum file size is 10 MB.", "danger")
            return redirect(url_for("dashboard"))

        s3.upload_fileobj(
            file,
            S3_BUCKET_NAME,
            s3_key,
            ExtraArgs={
                "ContentType": file.content_type or "application/octet-stream"
            }
        )

        conn = get_db()
        conn.execute(
            """
            INSERT INTO files
            (user_id, original_name, s3_key, content_type, size, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session["user_id"],
                original_name,
                s3_key,
                file.content_type or "application/octet-stream",
                file_size,
                datetime.now().isoformat()
            )
        )
        conn.commit()
        conn.close()

        flash("File uploaded successfully to AWS S3.", "success")

    except (BotoCoreError, ClientError) as exc:
        flash(f"AWS S3 error: {exc}", "danger")

    return redirect(url_for("dashboard"))


@app.route("/view/<int:file_id>")
@login_required
def view_file(file_id):
    file_row = get_owned_file(file_id)

    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": S3_BUCKET_NAME,
                "Key": file_row["s3_key"]
            },
            ExpiresIn=300,  # 5 minutes
        )
        return redirect(url)
    except (BotoCoreError, ClientError) as exc:
        flash(f"Unable to create file link: {exc}", "danger")
        return redirect(url_for("dashboard"))


@app.route("/download/<int:file_id>")
@login_required
def download_file(file_id):
    file_row = get_owned_file(file_id)

    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": S3_BUCKET_NAME,
                "Key": file_row["s3_key"],
                "ResponseContentDisposition":
                    f'attachment; filename="{file_row["original_name"]}"'
            },
            ExpiresIn=300,
        )
        return redirect(url)
    except (BotoCoreError, ClientError) as exc:
        flash(f"Unable to create download link: {exc}", "danger")
        return redirect(url_for("dashboard"))


@app.route("/share/<int:file_id>")
@login_required
def share_file(file_id):
    file_row = get_owned_file(file_id)

    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": S3_BUCKET_NAME,
                "Key": file_row["s3_key"]
            },
            ExpiresIn=3600,  # 1 hour
        )
        return render_template(
            "share.html",
            file=file_row,
            share_url=url
        )
    except (BotoCoreError, ClientError) as exc:
        flash(f"Unable to create share link: {exc}", "danger")
        return redirect(url_for("dashboard"))


@app.route("/delete/<int:file_id>", methods=["POST"])
@login_required
def delete_file(file_id):
    file_row = get_owned_file(file_id)

    try:
        s3.delete_object(
            Bucket=S3_BUCKET_NAME,
            Key=file_row["s3_key"]
        )

        conn = get_db()
        conn.execute(
            "DELETE FROM files WHERE id = ? AND user_id = ?",
            (file_id, session["user_id"])
        )
        conn.commit()
        conn.close()

        flash("File deleted from AWS S3.", "success")

    except (BotoCoreError, ClientError) as exc:
        flash(f"Unable to delete file: {exc}", "danger")

    return redirect(url_for("dashboard"))


@app.errorhandler(413)
def too_large(_error):
    flash("File is too large. Maximum allowed size is 10 MB.", "danger")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
