# War Zone Registration - Google Drive Storage

This patch makes uploaded registration images save to a Google Drive folder instead of only Railway local/volume storage.

## Files to replace/add

Replace only:

- `registration_routes.py`

Add these packages to your existing `requirements.txt`:

```txt
google-api-python-client
google-auth
google-auth-httplib2
```

No changes are required to the old War Zone pages.

## Railway variables

Add these variables in Railway:

```txt
GOOGLE_DRIVE_FOLDER_ID=<your_google_drive_folder_id>
GOOGLE_SERVICE_ACCOUNT_JSON_B64=<base64_service_account_json>
```

Optional:

```txt
GOOGLE_DRIVE_DELETE_ON_TEAM_DELETE=true
```

Keep your existing variables:

```txt
REGISTRATION_ADMIN_PASSWORD=BeshooWarZone
REGISTRATION_DATA_DIR=/app/registration_data
```

## Google Drive setup

1. Create or choose a Google Drive folder.
2. Copy the folder ID from the URL.
3. Create a Google Cloud service account and download its JSON key.
4. Share the Google Drive folder with the service account email as Editor.
5. Convert the JSON key to base64 and paste it in Railway variable `GOOGLE_SERVICE_ACCOUNT_JSON_B64`.

On Mac/Linux:

```bash
base64 -i service-account.json | pbcopy
```

If your terminal wraps lines, use:

```bash
base64 -i service-account.json | tr -d '\n' | pbcopy
```

On Windows PowerShell:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("service-account.json")) | Set-Clipboard
```

## Result

When a team registers, the system will create folders in Drive like:

```txt
Root Drive Folder
└── Team Name - teamid
    └── Player Name - playerid
        ├── photo_xxx.jpg
        ├── id_card_xxx.jpg
        └── university_card_xxx.jpg
```

The admin can still open files from `/registrations`; the app downloads them from Drive securely through the backend.
