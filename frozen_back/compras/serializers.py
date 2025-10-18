from rest_framework import serializers
from .models import OrdenCompra, EstadoOrdenCompra, OrdenCompraMateriaPrima, OrdenCompraProduccion
from materias_primas.models import Proveedor

class estadoOrdenCompraSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoOrdenCompra
        fields = "__all__"


class ordenCompraSerializer(serializers.ModelSerializer):
    estado_descripcion = serializers.CharField(source='id_estado_orden_compra.descripcion', read_only=True)
    proveedor_nombre = serializers.CharField(source='id_proveedor.nombre', read_only=True)

    class Meta:
        model = OrdenCompra
        fields = [
            "__all__"
        ]


class ordenCompraMateriaPrimaSerializer(serializers.ModelSerializer):
    materia_prima_nombre = serializers.CharField(source='id_materia_prima.nombre', read_only=True)

    class Meta:
        model = OrdenCompraMateriaPrima
        fields = [
            "__all__"
        ]

class ordenCompraProduccionSerializer(serializers.ModelSerializer):
    orden_produccion_detalle = serializers.CharField(source='id_orden_produccion.detalle', read_only=True)

    class Meta:
        model = OrdenCompraProduccion
        fields = [
            "__all__"
        ]