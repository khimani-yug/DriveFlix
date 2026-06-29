from django.urls import path
from . import views

urlpatterns = [
    path('', views.FolderView.as_view(), name='home'),
    path('folder/<str:folder_id>/', views.FolderView.as_view(), name='folder'),
    path('watch/<str:file_id>/', views.PlayerView.as_view(), name='player'),
    path('stream/<str:file_id>/', views.StreamView.as_view(), name='stream'),
    path('sync/', views.SyncMoviesView.as_view(), name='sync_movies'),
    path('api/search/', views.SearchAPIView.as_view(), name='search_api'),
    path('api/progress/update/', views.UpdateProgressAPIView.as_view(), name='update_progress'),
]
