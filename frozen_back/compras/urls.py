from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import orden_compra_materia_primaViewSet, ordenCompraViewSet, estadoOrdenCompraViewSet, orden_compra_produccionViewSet

router = DefaultRouter()
router.register(r'estados', estadoOrdenCompraViewSet)
router.register(r'compras', ordenCompraViewSet)
router.register(r'compra-produccion', orden_compra_produccionViewSet)
router.register(r'compra-materia', orden_compra_materia_primaViewSet)

urlpatterns = [
    path('', include(router.urls)),
]