from rest_framework import serializers
from .models import orden_compra, estado_orden_compra, orden_compra_materia_prima, orden_compra_produccion
from materias_primas.models import Proveedor

class estadoOrdenCompraSerializer(serializers.ModelSerializer):
    class Meta:
        model = estado_orden_compra
        fields = "__all__"


class ordenCompraSerializer(serializers.ModelSerializer):
    estado_descripcion = serializers.CharField(source='id_estado_orden_compra.descripcion', read_only=True)
    proveedor_nombre = serializers.CharField(source='id_proveedor.nombre', read_only=True)

    class Meta:
        model = orden_compra
        fields = [
            "__all__"
        ]


class ordenCompraMateriaPrimaSerializer(serializers.ModelSerializer):
    materia_prima_nombre = serializers.CharField(source='id_materia_prima.nombre', read_only=True)

    class Meta:
        model = orden_compra_materia_prima
        fields = [
            "__all__"
        ]

class ordenCompraProduccionSerializer(serializers.ModelSerializer):
    orden_produccion_detalle = serializers.CharField(source='id_orden_produccion.detalle', read_only=True)

    class Meta:
        model = orden_compra_produccion
        fields = [
            "__all__"
        ]