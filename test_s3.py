import boto3

BUCKET_NAME = "cloud-file-storage12"
FILE_NAME = "sample.txt"

s3 = boto3.client("s3")

s3.upload_file(FILE_NAME, BUCKET_NAME, FILE_NAME)

print(f"{FILE_NAME} uploaded successfully to {BUCKET_NAME}")