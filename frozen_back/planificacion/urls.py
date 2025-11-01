from django.urls import path
from . import views

urlpatterns = [
    # Registra la vista en la URL 'api/planificacion/ejecutar/'
    path('ejecutar/', views.ejecutar_planificacion_view, name='ejecutar-planificacion'),
]