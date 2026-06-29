import os
import re
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from movies.models import Folder, Movie

class Command(BaseCommand):
    help = "Syncs nested movie and folder structures recursively from Google Drive to the local database"

    def fetch_movie_poster(self, title):
        """
        Cleans filename titles and queries TMDB API to fetch movie posters.
        Returns poster image URL if found, else None.
        
        To fully configure this feature, set TMDB_API_KEY inside your .env file.
        """
        api_key = getattr(settings, 'TMDB_API_KEY', os.getenv('TMDB_API_KEY', ''))
        if not api_key:
            return None

        # Basic filename cleaning (removes standard torrent metadata brackets, dates, formats)
        clean_title = title.split(' (')[0]
        clean_title = clean_title.split('.20')[0].split('.19')[0]  # strip year groups
        clean_title = clean_title.replace('.', ' ').replace('-', ' ').replace('_', ' ')
        clean_title = ' '.join(clean_title.split())  # strip whitespace

        try:
            # Query TMDB Search Endpoint
            search_url = "https://api.themoviedb.org/3/search/movie"
            params = {
                'api_key': api_key,
                'query': clean_title,
                'language': 'en-US',
                'page': 1
            }
            response = requests.get(search_url, params=params, timeout=5)
            if response.status_code == 200:
                results = response.json().get('results', [])
                if results:
                    poster_path = results[0].get('poster_path')
                    if poster_path:
                        return f"https://image.tmdb.org/t/p/w500{poster_path}"
        except Exception as e:
            self.stdout.write(f"  [TMDB API Error] Failed to fetch poster for '{clean_title}': {e}")
        
        return None

    def handle(self, *args, **options):
        root_folder_id = getattr(settings, 'GOOGLE_DRIVE_FOLDER_ID', None)
        creds_json = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON', '')

        if not root_folder_id or root_folder_id == "your_google_drive_folder_id_here":
            self.stderr.write("Error: GOOGLE_DRIVE_FOLDER_ID is not configured in settings or .env file.")
            return

        if not creds_json and (not creds_path or not os.path.exists(creds_path)):
            self.stderr.write("Error: Google Service Account credentials not found in env variable or JSON file.")
            return

        self.stdout.write("Connecting to Google Drive API...")

        try:
            if creds_json:
                import json
                credentials = service_account.Credentials.from_service_account_info(
                    json.loads(creds_json),
                    scopes=['https://www.googleapis.com/auth/drive.readonly']
                )
            else:
                credentials = service_account.Credentials.from_service_account_file(
                    creds_path,
                    scopes=['https://www.googleapis.com/auth/drive.readonly']
                )
            service = build('drive', 'v3', credentials=credentials)
            
            active_folder_ids = set()
            active_file_ids = set()

            try:
                root_metadata = service.files().get(fileId=root_folder_id, fields="name").execute()
                root_name = root_metadata.get('name', 'Home')
            except Exception:
                root_name = 'Home'
            
            root_folder, _ = Folder.objects.update_or_create(
                folder_id=root_folder_id,
                defaults={'name': root_name, 'parent': None}
            )
            active_folder_ids.add(root_folder_id)

            stack = [(root_folder_id, root_folder)]

            self.stdout.write("Starting recursive sync of folders and video files...")

            while len(stack) > 0:
                current_id, current_folder_obj = stack.pop()
                try:
                    self.stdout.write(f"Scanning folder: {current_folder_obj.name} ({current_id})")
                except UnicodeEncodeError:
                    self.stdout.write(f"Scanning folder: {current_folder_obj.name.encode('ascii', 'ignore').decode('ascii')} ({current_id})")

                query = f"'{current_id}' in parents and trashed = false"
                fields = "nextPageToken, files(id, name, mimeType, size, thumbnailLink)"
                page_token = None

                while True:
                    response = service.files().list(
                        q=query,
                        spaces='drive',
                        fields=fields,
                        pageToken=page_token,
                        pageSize=100
                    ).execute()

                    items = response.get('files', [])
                    for item in items:
                        item_id = item.get('id')
                        name = item.get('name')
                        mime_type = item.get('mimeType')

                        if mime_type == 'application/vnd.google-apps.folder':
                            folder_obj, _ = Folder.objects.update_or_create(
                                folder_id=item_id,
                                defaults={
                                    'name': name,
                                    'parent': current_folder_obj
                                }
                            )
                            active_folder_ids.add(item_id)
                            stack.append((item_id, folder_obj))

                        elif 'video/' in mime_type:
                            size_bytes = int(item.get('size', 0))
                            thumbnail_link = item.get('thumbnailLink', '')
                            display_name, _ = os.path.splitext(name)

                            # Fetch TMDB poster if possible
                            poster_link = self.fetch_movie_poster(display_name)

                            Movie.objects.update_or_create(
                                file_id=item_id,
                                defaults={
                                    'name': name,
                                    'display_name': display_name,
                                    'mime_type': mime_type,
                                    'size_bytes': size_bytes,
                                    'thumbnail_link': thumbnail_link,
                                    'poster_link': poster_link,
                                    'folder': current_folder_obj
                                }
                            )
                            active_file_ids.add(item_id)
                            try:
                                self.stdout.write(f"  * Video: {display_name}")
                            except UnicodeEncodeError:
                                self.stdout.write(f"  * Video: {display_name.encode('ascii', 'ignore').decode('ascii')}")

                    page_token = response.get('nextPageToken', None)
                    if not page_token:
                        break

            # Cleanup step
            deleted_movies_count, _ = Movie.objects.exclude(file_id__in=active_file_ids).delete()
            deleted_folders_count, _ = Folder.objects.exclude(folder_id__in=active_folder_ids).delete()

            if deleted_movies_count > 0:
                self.stdout.write("Removed deleted movies from database.")
            if deleted_folders_count > 0:
                self.stdout.write("Removed deleted folders from database.")

            self.stdout.write(self.style.SUCCESS("Database sync completed successfully!"))

        except HttpError as error:
            self.stderr.write(self.style.ERROR(f"Google Drive API returned an error: {error}"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"An unexpected error occurred: {e}"))
