from django.urls import path
from . import views

urlpatterns = [
    path('', views.upload_view, name='upload'),
    path('preview/', views.preview_excel, name='preview_excel'),
]