from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    EstadoOrdenProduccionViewSet,
    LineaProduccionViewSet,
    OrdenProduccionViewSet,
    NoConformidadViewSet
)

router = DefaultRouter()
router.register(r'estados', EstadoOrdenProduccionViewSet)
router.register(r'lineas', LineaProduccionViewSet)
router.register(r'ordenes', OrdenProduccionViewSet)
router.register(r'noconformidades', NoConformidadViewSet)
router.register(r'estado_linea_produccion', LineaProduccionViewSet)  

urlpatterns = [
    path('', include(router.urls)),
]