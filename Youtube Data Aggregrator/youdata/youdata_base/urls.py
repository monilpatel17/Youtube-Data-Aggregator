from django.contrib import admin
from django.urls import path
from youdata_base import views

urlpatterns = [
    path("", views.index, name = "home"),
    path('youtube/', views.index),

    
]
