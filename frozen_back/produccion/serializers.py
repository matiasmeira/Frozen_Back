from rest_framework import serializers
from .models import EstadoOrdenProduccion, LineaProduccion, OrdenProduccion, NoConformidad
from empleados.models import Empleado
from productos.models import Producto
from stock.models import LoteProduccion, EstadoLoteProduccion

# ------------------------------
# Serializers básicos
# ------------------------------
class EstadoOrdenProduccionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoOrdenProduccion
        fields = '__all__'

class LineaProduccionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LineaProduccion
        fields = '__all__'

class EmpleadoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Empleado
        fields = ['id_empleado', 'nombre', 'apellido']

class ProductoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Producto
        fields = ['id_producto', 'nombre', 'descripcion', 'dias_duracion']

class EstadoLoteProduccionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoLoteProduccion
        fields = ['id_estado_lote_produccion', 'descripcion']

class LoteProduccionSerializer(serializers.ModelSerializer):
    id_estado_lote_produccion = EstadoLoteProduccionSerializer()
    id_producto = ProductoSerializer()

    class Meta:
        model = LoteProduccion
        fields = ['id_lote_produccion', 'id_producto', 'fecha_produccion', 'fecha_vencimiento', 'cantidad', 'id_estado_lote_produccion']

# ------------------------------
# Serializer principal de OrdenProduccion
# ------------------------------

class OrdenProduccionCreateSerializer(serializers.ModelSerializer):
    id_estado_orden_produccion = serializers.PrimaryKeyRelatedField(read_only=True)  
    
    class Meta:
        model = OrdenProduccion
        fields = '__all__'

class OrdenProduccionSerializer(serializers.ModelSerializer):
    id_estado_orden_produccion = EstadoOrdenProduccionSerializer(read_only=True)
    id_linea_produccion = LineaProduccionSerializer(read_only=True)
    id_supervisor = EmpleadoSerializer(read_only=True)
    id_operario = EmpleadoSerializer(read_only=True)
    id_producto = ProductoSerializer(read_only=True)
    id_lote_produccion = LoteProduccionSerializer(read_only=True)

    class Meta:
        model = OrdenProduccion
        fields = '__all__'

# ------------------------------
# Serializer de NoConformidad
# ------------------------------
class NoConformidadSerializer(serializers.ModelSerializer):
    class Meta:
        model = NoConformidad
        fields = '__all__'