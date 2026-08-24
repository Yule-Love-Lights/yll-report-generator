"""Google Drive helpers: read raw transcripts, read/write reports."""
import io
import json
import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.oauth2 import service_account

SCOPES = ['https://www.googleapis.com/auth/drive']


def get_drive_service():
    creds_json = json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON'])
    creds = service_account.Credentials.from_service_account_info(creds_json, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)


def list_files(drive, folder_id, name_prefix=None):
    """List files in a Shared Drive folder, optionally filtered by filename prefix."""
    query = f"'{folder_id}' in parents and trashed = false"
    if name_prefix:
        query += f" and name contains '{name_prefix}'"
    results = []
    page_token = None
    while True:
        res = drive.files().list(
            q=query,
            fields='nextPageToken, files(id, name, createdTime)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora='allDrives',
            pageToken=page_token,
        ).execute()
        results.extend(res.get('files', []))
        page_token = res.get('nextPageToken')
        if not page_token:
            break
    return results


def download_text(drive, file_id):
    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue().decode('utf-8', errors='replace')


def download_bytes(drive, file_id):
    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def upload_docx(drive, folder_id, filename, docx_bytes):
    media = MediaIoBaseUpload(
        io.BytesIO(docx_bytes),
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        resumable=True,
        chunksize=1024 * 1024,  # 1MB chunks
    )
    request = drive.files().create(
        body={'name': filename, 'parents': [folder_id]},
        media_body=media,
        fields='id, webViewLink',
        supportsAllDrives=True,
    )
    file = None
    while file is None:
        status, file = request.next_chunk(num_retries=5)
    return file


def delete_files_with_prefix(drive, folder_id, name_prefix):
    """Deletes all files in a folder whose name starts with name_prefix.
    Used to clear out any existing daily-state file(s) before writing a
    fresh one, so re-running the daily job never leaves duplicates."""
    existing = list_files(drive, folder_id, name_prefix=name_prefix)
    for f in existing:
        drive.files().delete(fileId=f['id'], supportsAllDrives=True).execute()
    return len(existing)
    payload = json.dumps(data_dict, indent=2).encode('utf-8')
    media = MediaIoBaseUpload(io.BytesIO(payload), mimetype='application/json')
    file = drive.files().create(
        body={'name': filename, 'parents': [folder_id]},
        media_body=media,
        fields='id',
        supportsAllDrives=True,
    ).execute(num_retries=5)
    return file


def download_json(drive, file_id):
    text = download_text(drive, file_id)
    return json.loads(text)
