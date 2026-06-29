from django.db import models

class Folder(models.Model):
    folder_id = models.CharField(max_length=255, unique=True, verbose_name="Google Drive Folder ID")
    name = models.CharField(max_length=255, verbose_name="Folder Name")
    parent = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='subfolders',
        verbose_name="Parent Folder"
    )
    synced_at = models.DateTimeField(auto_now=True, verbose_name="Last Synced At")

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_breadcrumbs(self):
        path = []
        current = self
        while current is not None:
            path.insert(0, current)
            current = current.parent
        return path


class Movie(models.Model):
    file_id = models.CharField(max_length=255, unique=True, verbose_name="Google Drive File ID")
    name = models.CharField(max_length=255, verbose_name="File Name")
    display_name = models.CharField(max_length=255, verbose_name="Display Title")
    mime_type = models.CharField(max_length=100, verbose_name="MIME Type")
    size_bytes = models.BigIntegerField(verbose_name="Size in Bytes", default=0)
    thumbnail_link = models.URLField(max_length=1000, blank=True, null=True, verbose_name="Thumbnail Link")
    poster_link = models.URLField(max_length=1000, blank=True, null=True, verbose_name="Rich Cover Art Link")
    folder = models.ForeignKey(
        Folder, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='movies',
        verbose_name="Containing Folder"
    )
    synced_at = models.DateTimeField(auto_now=True, verbose_name="Last Synced At")

    class Meta:
        ordering = ['display_name']

    def __str__(self):
        return self.display_name

    @property
    def human_readable_size(self):
        size = self.size_bytes
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"


class VideoProgress(models.Model):
    session_id = models.CharField(max_length=255, db_index=True)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='progress_records')
    current_time_seconds = models.FloatField(default=0.0)
    duration_seconds = models.FloatField(default=0.0)
    last_watched = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('session_id', 'movie')
        ordering = ['-last_watched']

    def __str__(self):
        return f"Session {self.session_id[:8]} watching {self.movie.display_name}"

    @property
    def percentage(self):
        if self.duration_seconds > 0:
            return min(100.0, (self.current_time_seconds / self.duration_seconds) * 100.0)
        return 0.0
