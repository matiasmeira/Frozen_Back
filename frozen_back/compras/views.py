from django.shortcuts import render

from frozen_back.compras.models import estado_orden_compra, orden_compra, orden_compra_produccion
from frozen_back.compras.serializers import estadoOrdenCompraSerializer, ordenCompraProduccionSerializer, ordenCompraSerializer
from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend

class ordenCompraViewSet(viewsets.ModelViewSet):
    queryset = orden_compra.objects.all()
    serializer_class = ordenCompraSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["fecha", "proveedor", "estado"]
    search_fields = ["proveedor__nombre", "estado", "numero_orden"]

class estadoOrdenCompraViewSet(viewsets.ModelViewSet):
    queryset = estado_orden_compra.objects.all()
    serializer_class = estadoOrdenCompraSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["descripcion"]
    search_fields = ["descripcion"]

class orden_compra_produccionViewSet(viewsets.ModelViewSet):
    queryset = orden_compra_produccion.objects.all()
    serializer_class = ordenCompraProduccionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["id_orden_compra", "id_orden_produccion"]
    search_fields = ["id_orden_compra__numero_orden", "id_orden_produccion__codigo"]

class orden_compra_materia_primaViewSet(viewsets.ModelViewSet):
    queryset = orden_compra_produccion.objects.all()
    serializer_class = ordenCompraProduccionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["id_orden_compra", "id_materia_prima"]
    search_fields = ["id_orden_compra__numero_orden", "id_materia_prima__nombre"]