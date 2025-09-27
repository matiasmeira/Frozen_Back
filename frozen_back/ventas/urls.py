from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import EstadoVentaViewSet, ClienteViewSet, OrdenVentaViewSet, OrdenVentaProductoViewSet

router = DefaultRouter()
router.register(r'estados-venta', EstadoVentaViewSet)
router.register(r'clientes', ClienteViewSet)
router.register(r'ordenes-venta', OrdenVentaViewSet)
router.register(r'ordenes-productos', OrdenVentaProductoViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
