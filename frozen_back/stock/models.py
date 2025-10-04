from django.db import models
from productos.models import Producto
from materias_primas.models import MateriaPrima

class EstadoLoteProduccion(models.Model):
    id_estado_lote_produccion = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = "estado_lote_produccion"


class EstadoLoteMateriaPrima(models.Model):
    id_estado_lote_materia_prima = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = "estado_lote_materia_prima"


class LoteProduccion(models.Model):
    id_lote_produccion = models.AutoField(primary_key=True)
    id_producto = models.ForeignKey(Producto, on_delete=models.CASCADE, db_column="id_producto")
    fecha_produccion = models.DateField(blank=True, null=True)
    fecha_vencimiento = models.DateField(blank=True, null=True)
    cantidad = models.IntegerField()
    id_estado_lote_produccion = models.ForeignKey(EstadoLoteProduccion, on_delete=models.CASCADE, db_column="id_estado_lote_produccion")

    class Meta:
        db_table = "lote_produccion"


class LoteMateriaPrima(models.Model):
    id_lote_materia_prima = models.AutoField(primary_key=True)
    id_materia_prima = models.ForeignKey(MateriaPrima, on_delete=models.CASCADE, db_column="id_materia_prima")
    fecha_vencimiento = models.DateField(blank=True, null=True)
    cantidad = models.IntegerField()
    id_estado_lote_materia_prima = models.ForeignKey(EstadoLoteMateriaPrima, on_delete=models.CASCADE, db_column="id_estado_lote_materia_prima")

    class Meta:
        db_table = "lote_materia_prima"


class LoteProduccionMateria(models.Model):
    id_lote_produccion_materia = models.AutoField(primary_key=True)
    id_lote_produccion = models.ForeignKey(LoteProduccion, on_delete=models.CASCADE, db_column="id_lote_produccion")
    id_lote_materia_prima = models.ForeignKey(LoteMateriaPrima, on_delete=models.CASCADE, db_column="id_lote_materia_prima")
    cantidad_usada = models.IntegerField()

    class Meta:
        db_table = "lote_produccion_materia"
