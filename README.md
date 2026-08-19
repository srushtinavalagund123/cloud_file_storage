# Cloud File Storage System - AWS S3

A Flask + SQLite + AWS S3 project for Task 1.

## Features

- User registration and login
- Secure password hashing
- Upload files to private AWS S3
- File validation
- 10 MB upload limit
- View files using temporary S3 URLs
- Download files
- Delete files
- User-specific file ownership
- Temporary shareable links
- SQLite metadata database
- Bootstrap UI

## 1. Install packages

```bash
pip install -r requirements.txt
```

## 2. Configure AWS

Create `.env` from `.env.example`:

```text
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=ap-south-1
S3_BUCKET_NAME=...
FLASK_SECRET_KEY=...
```

Never commit `.env` to GitHub.

## 3. AWS permissions

The IAM identity used by the application should have only the required S3 permissions:
- s3:ListBucket
- s3:PutObject
- s3:GetObject
- s3:DeleteObject

Keep the S3 bucket private.

## 4. Run

```bash
python app.py
```

Open:

http://127.0.0.1:5000

## 5. Test

1. Register a user.
2. Login.
3. Upload a file.
4. Verify it appears in S3.
5. View/download the file.
6. Generate a share link.
7. Delete the file.
