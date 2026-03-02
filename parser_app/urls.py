from django.urls import path
from . import views

urlpatterns = [
    path('', views.upload_view, name='upload'),
    path('preview/', views.preview_excel, name='preview_excel'),
    path('process/', views.start_processing_view, name='start_processing'),
    path('progress/<str:task_id>/', views.get_progress_view, name='get_progress'),
    path('cancel/<str:task_id>/', views.cancel_processing_view, name='cancel_processing'),
    path('results/<str:task_id>/', views.results_view, name='results'),
]