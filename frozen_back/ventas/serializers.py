from rest_framework import serializers
from .models import EstadoVenta, Cliente, OrdenVenta, OrdenVentaProducto

class EstadoVentaSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoVenta
        fields = '__all__'


class ClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = '__all__'


class OrdenVentaSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrdenVenta
        fields = '__all__'


class OrdenVentaProductoSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrdenVentaProducto
        fields = '__all__'
