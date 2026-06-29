import re
import json
import requests
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import View
from django.http import StreamingHttpResponse, Http404, JsonResponse
from django.conf import settings
from django.core.management import call_command
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleAuthRequest
from movies.models import Folder, Movie, VideoProgress

class FolderView(View):
    def get(self, request, folder_id=None, *args, **kwargs):
        root_id = getattr(settings, 'GOOGLE_DRIVE_FOLDER_ID', '')
        current_id = folder_id if folder_id else root_id
        
        if not current_id:
            return render(request, 'movies/home.html', {
                'folder': None, 'subfolders': [], 'movies': [], 'breadcrumbs': []
            })
            
        # Try to find the folder object. If it doesn't exist, we likely haven't synced yet.
        # Handle this gracefully instead of throwing a 404 error on the index route.
        try:
            folder_obj = Folder.objects.get(folder_id=current_id)
        except Folder.DoesNotExist:
            if current_id == root_id:
                # If we're hitting the root index and it's not in the DB, show an empty home view
                # with instructions to run sync.
                return render(request, 'movies/home.html', {
                    'folder': None, 'subfolders': [], 'movies': [], 'breadcrumbs': [], 'is_root': True
                })
            else:
                raise Http404("Folder not found. Please sync the database.")
        subfolders = folder_obj.subfolders.all()
        movies = folder_obj.movies.all()
        breadcrumbs = folder_obj.get_breadcrumbs()
        is_root = (current_id == root_id)

        # Retrieve session-based video progress for these movies
        if not request.session.session_key:
            request.session.create()
        session_id = request.session.session_key

        progress_map = {}
        if session_id:
            progress_qs = VideoProgress.objects.filter(session_id=session_id, movie__in=movies)
            for prog in progress_qs:
                progress_map[prog.movie_id] = prog.percentage

        # Attach progress percentages to movies context dynamically
        for movie in movies:
            movie.watch_progress_percentage = progress_map.get(movie.id, 0.0)

        return render(request, 'movies/home.html', {
            'folder': folder_obj,
            'subfolders': subfolders,
            'movies': movies,
            'breadcrumbs': breadcrumbs,
            'is_root': is_root,
        })

class PlayerView(View):
    def get(self, request, file_id, *args, **kwargs):
        movie = get_object_or_404(Movie, file_id=file_id)
        breadcrumbs = []
        if movie.folder:
            breadcrumbs = movie.folder.get_breadcrumbs()

        # Find next sequential movie in same folder
        next_movie = None
        is_series = False
        if movie.folder:
            next_movie = Movie.objects.filter(
                folder=movie.folder, 
                display_name__gt=movie.display_name
            ).order_by('display_name').first()
            
            # Only display the next episode button if the movie lives inside a "Series" section.
            # We verify this by walking up the breadcrumbs to check if any parent folder is named "Series".
            has_series_parent = False
            for crumb in breadcrumbs:
                if crumb.name.strip().lower() == 'series':
                    has_series_parent = True
                    break

            if has_series_parent:
                # Find matching sequence names inside the series child folder
                other_movies = movie.folder.movies.exclude(id=movie.id)
                
                def get_clean_tokens(title):
                    tokens = re.split(r'[\s\.\-\_\(\)\[\]\{\}]+', title.lower())
                    generic = {'mp4', 'mkv', 'webm', 'hevc', 'x264', 'x265', '1080p', '720p', 'web', 'dl', 'bluray', 'esub', 'hindi', 'english', 'tamil', 'telugu', 'dual', 'audio', 'season', 'episode', 'series'}
                    return [t for t in tokens if t and t not in generic and not t.isdigit()]

                current_tokens = get_clean_tokens(movie.display_name)
                
                for other in other_movies:
                    other_tokens = get_clean_tokens(other.display_name)
                    common_prefix = []
                    for t1, t2 in zip(current_tokens, other_tokens):
                        if t1 == t2:
                            common_prefix.append(t1)
                        else:
                            break
                    
                    if len(common_prefix) >= 2 or (len(common_prefix) >= 1 and any(x in movie.display_name.lower() for x in ['s0', 's1', 's2', 's3', 's4', 's5', 'e0', 'e1', 'ep'])):
                        is_series = True
                        break

        # Load existing progress if any
        if not request.session.session_key:
            request.session.create()
        session_id = request.session.session_key
        
        saved_progress_seconds = 0.0
        if session_id:
            progress_obj = VideoProgress.objects.filter(session_id=session_id, movie=movie).first()
            if progress_obj:
                saved_progress_seconds = progress_obj.current_time_seconds

        return render(request, 'movies/player.html', {
            'movie': movie,
            'breadcrumbs': breadcrumbs,
            'next_movie': next_movie,
            'is_series': is_series,
            'saved_progress_seconds': saved_progress_seconds,
        })

class SyncMoviesView(View):
    def post(self, request, *args, **kwargs):
        try:
            call_command('sync_movies')
            return JsonResponse({'status': 'success', 'message': 'Movies synced successfully!'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

class SearchAPIView(View):
    def get(self, request, *args, **kwargs):
        query = request.GET.get('q', '').strip()
        if not query:
            return JsonResponse({'movies': [], 'folders': []})

        folders_qs = Folder.objects.filter(name__icontains=query)[:5]
        folders_data = [
            {
                'folder_id': f.folder_id,
                'name': f.name
            } for f in folders_qs
        ]

        movies_qs = Movie.objects.filter(display_name__icontains=query)[:5]
        movies_data = [
            {
                'file_id': m.file_id,
                'name': m.display_name,
                'parent_folder_id': m.folder.folder_id if m.folder else None
            } for m in movies_qs
        ]

        return JsonResponse({
            'movies': movies_data,
            'folders': folders_data
        })

@method_decorator(csrf_exempt, name='dispatch')
class UpdateProgressAPIView(View):
    def post(self, request, *args, **kwargs):
        if not request.session.session_key:
            request.session.create()
        session_id = request.session.session_key
        
        try:
            data = json.loads(request.body)
            file_id = data.get('file_id')
            current_time = float(data.get('current_time', 0))
            duration = float(data.get('duration', 0))

            if not file_id:
                return JsonResponse({'status': 'error', 'message': 'Missing file_id'}, status=400)

            movie = get_object_or_404(Movie, file_id=file_id)
            
            # Save or update progress
            VideoProgress.objects.update_or_create(
                session_id=session_id,
                movie=movie,
                defaults={
                    'current_time_seconds': current_time,
                    'duration_seconds': duration
                }
            )
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

class StreamView(View):
    def get(self, request, file_id, *args, **kwargs):
        movie = get_object_or_404(Movie, file_id=file_id)
        # 1. Fetch credentials dynamically from file path or raw environment JSON string
        creds_json = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON', '')
        creds_path = getattr(settings, 'GOOGLE_APPLICATION_CREDENTIALS', None)
        
        try:
            if creds_json:
                import json
                import ast
                cleaned_json = creds_json.strip()
                if (cleaned_json.startswith('"') and cleaned_json.endswith('"')) or (cleaned_json.startswith("'") and cleaned_json.endswith("'")):
                    try:
                        cleaned_json = ast.literal_eval(cleaned_json)
                    except Exception:
                        pass
                
                # Replace literal control characters (newlines) which crash JSON parsing in standard environments
                cleaned_json = cleaned_json.replace('\n', ' ').replace('\r', ' ')
                
                credentials = service_account.Credentials.from_service_account_info(
                    json.loads(cleaned_json),
                    scopes=['https://www.googleapis.com/auth/drive.readonly']
                )
            elif creds_path and os.path.exists(creds_path):
                credentials = service_account.Credentials.from_service_account_file(
                    creds_path,
                    scopes=['https://www.googleapis.com/auth/drive.readonly']
                )
            else:
                raise Http404("Google Application Credentials are not configured.")
                
            credentials.refresh(GoogleAuthRequest())
            access_token = credentials.token
        except Exception as e:
            raise Http404(f"Authentication with Google Drive failed: {e}")

        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        range_header = request.headers.get('Range', None)
        file_size = movie.size_bytes
        status_code = 200
        
        if range_header:
            match = re.search(r'bytes=(\d+)-(\d*)', range_header)
            if match:
                start_byte = int(match.group(1))
                end_byte = match.group(2)
                end_byte = int(end_byte) if end_byte else file_size - 1
                
                if start_byte >= file_size:
                    start_byte = file_size - 1
                if end_byte >= file_size:
                    end_byte = file_size - 1
                
                headers['Range'] = f"bytes={start_byte}-{end_byte}"
                status_code = 206
                content_length = (end_byte - start_byte) + 1
                content_range = f"bytes {start_byte}-{end_byte}/{file_size}"
            else:
                start_byte = 0
                end_byte = file_size - 1
                content_length = file_size
                content_range = f"bytes 0-{end_byte}/{file_size}"
        else:
            start_byte = 0
            end_byte = file_size - 1
            content_length = file_size
            content_range = f"bytes 0-{end_byte}/{file_size}"

        try:
            drive_response = requests.get(url, headers=headers, stream=True, timeout=30)
            if drive_response.status_code not in [200, 206]:
                drive_response = requests.get(url, headers={"Authorization": f"Bearer {access_token}"}, stream=True, timeout=30)
                status_code = 200
                content_length = file_size
        except Exception as e:
            raise Http404(f"Failed to connect to Google Drive: {e}")

        def file_iterator(response, chunk_size=8192*8):
            try:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        yield chunk
            finally:
                response.close()

        response = StreamingHttpResponse(
            file_iterator(drive_response),
            status=status_code,
            content_type=movie.mime_type
        )
        
        response['Accept-Ranges'] = 'bytes'
        response['Content-Length'] = content_length
        if status_code == 206:
            response['Content-Range'] = content_range
            
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'

        return response
