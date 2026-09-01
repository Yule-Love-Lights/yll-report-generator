"""Google Drive helpers: read raw transcripts, read/write reports."""
import io
import json
import os
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
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


def find_by_name(drive, folder_id, filename):
    """The one file in folder_id named exactly filename, or None."""
    for f in list_files(drive, folder_id, name_prefix=filename):
        if f['name'] == filename:
            return f
    return None


def _upsert(drive, folder_id, filename, media, fields='id'):
    """Writes filename in folder_id, replacing its contents if it exists.

    Deliberately NOT delete-then-create. Drive's file *list* is only
    eventually consistent with its file *store*, so a just-listed id can
    404 on delete — which it did, aborting a monthly rollup between the
    delete and the upload. Updating in place keeps one stable id and has
    no window where the file is missing or duplicated.
    """
    existing = find_by_name(drive, folder_id, filename)
    if existing:
        try:
            return drive.files().update(
                fileId=existing['id'], media_body=media, fields=fields,
                supportsAllDrives=True,
            ).execute(num_retries=5)
        except HttpError as e:
            if e.resp.status != 404:
                raise
            # Listing was stale; fall through and create a fresh one.
    return drive.files().create(
        body={'name': filename, 'parents': [folder_id]},
        media_body=media, fields=fields, supportsAllDrives=True,
    ).execute(num_retries=5)


def upload_docx(drive, folder_id, filename, docx_bytes):
    media = MediaIoBaseUpload(
        io.BytesIO(docx_bytes),
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        resumable=True,
        chunksize=1024 * 1024,  # 1MB chunks
    )
    return _upsert(drive, folder_id, filename, media, fields='id, webViewLink')


def delete_files_with_prefix(drive, folder_id, name_prefix):
    """Deletes all files in a folder whose name starts with name_prefix.

    A 404 is treated as success — the file being gone is the outcome this
    asks for, and a stale listing must not abort the caller.
    """
    deleted = 0
    for f in list_files(drive, folder_id, name_prefix=name_prefix):
        try:
            drive.files().delete(
                fileId=f['id'], supportsAllDrives=True).execute(num_retries=5)
            deleted += 1
        except HttpError as e:
            if e.resp.status != 404:
                raise
    return deleted


def upload_json(drive, folder_id, filename, data_dict):
    payload = json.dumps(data_dict, indent=2).encode('utf-8')
    media = MediaIoBaseUpload(io.BytesIO(payload), mimetype='application/json')
    return _upsert(drive, folder_id, filename, media)


def download_json(drive, file_id):
    text = download_text(drive, file_id)
    return json.loads(text)
