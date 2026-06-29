# DriveFlix 🎬

**DriveFlix** is a private, cloud-powered streaming portal built on Django. It securely interfaces with a private Google Drive repository via a custom backend proxy, serving nested directories recursively. Features include live AJAX search, real-time video progress tracking, and smooth HTML5 Video.js streaming with range-seeking.

Developed by **Yug Khimani**.

---

## Features

- **Nested Folder Support**: Recursively sync and navigate your Google Drive folders (e.g., TV Series -> Season -> Episode files).
- **Responsive Theater Mode**: Fully responsive Tailwind CSS layout featuring a centered Video.js player styled with red accents.
- **Bookmarks & Autoplay**: Tracks video playback progress to let you resume from where you left off, and plays the next sequential video automatically.
- **Global Search**: Search across movies and directories instantly from the navigation bar.

---

## Quick Start

### 1. Install Dependencies
Make sure you have your virtual environment activated, then run:
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Create a `.env` file in the root folder and add your configuration details:
```env
GOOGLE_DRIVE_FOLDER_ID=your_drive_folder_id
GOOGLE_APPLICATION_CREDENTIALS=credentials/service_account.json
SECRET_KEY=your_django_secret_key
DEBUG=True
ALLOWED_HOSTS=*
```

### 3. Service Account Credentials
1. Save your Google Cloud Platform Service Account JSON file as `credentials/service_account.json`.
2. Share your Google Drive Folder with the Service Account email address as a **Viewer**.

### 4. Database Setup & Sync
Run Django migrations to create the database models, then run the sync command to pull files metadata from Google Drive:
```bash
python manage.py migrate
python manage.py sync_movies
```

### 5. Start Development Server
```bash
python manage.py runserver
```
Visit `http://localhost:8000` in your web browser.
