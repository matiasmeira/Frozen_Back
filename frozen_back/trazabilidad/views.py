from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .services import get_traceability_backward, get_traceability_forward
from .services import get_traceability_backward, get_traceability_forward, get_traceability_for_order

class TrazabilidadViewSet(viewsets.ViewSet):
    """
    ViewSet para realizar consultas de trazabilidad.
    No está basado en un modelo, solo proporciona acciones.
    """

    @action(detail=False, methods=['get'], url_path='hacia-atras')
    def trace_backward(self, request):
        """
        Trazabilidad hacia atrás.
        Requiere: ?id_ovp=<id_orden_venta_producto>
        """
        id_ovp = request.query_params.get('id_ovp')
        if not id_ovp:
            return Response(
                {"error": "Debe proporcionar el parámetro 'id_ovp' (ID de OrdenVentaProducto)"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        report = get_traceability_backward(int(id_ovp))
        if 'error' in report:
            return Response(report, status=status.HTTP_404_NOT_FOUND)
        
        return Response(report, status=status.HTTP_200_OK)


    @action(detail=False, methods=['get'], url_path='hacia-adelante')
    def trace_forward(self, request):
        """
        Trazabilidad hacia adelante.
        Requiere: ?id_lote_mp=<id_lote_materia_prima>
        """
        id_lote_mp = request.query_params.get('id_lote_mp')
        if not id_lote_mp:
            return Response(
                {"error": "Debe proporcionar el parámetro 'id_lote_mp' (ID de LoteMateriaPrima)"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        report = get_traceability_forward(int(id_lote_mp))
        if 'error' in report:
            return Response(report, status=status.HTTP_404_NOT_FOUND)
            
        return Response(report, status=status.HTTP_200_OK)
    

    @action(detail=False, methods=['get'], url_path='por-orden-venta')
    def trace_by_order(self, request):
        """
        Trazabilidad hacia atrás para una orden de venta COMPLETA.
        Requiere: ?id_ov=<id_orden_venta>
        """
        # Usamos 'id_ov' para diferenciarlo de 'id_ovp'
        id_ov = request.query_params.get('id_ov') 
        
        if not id_ov:
            return Response(
                {"error": "Debe proporcionar el parámetro 'id_ov' (ID de OrdenVenta)"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Llamamos al NUEVO servicio
        report = get_traceability_for_order(int(id_ov))
        
        if 'error' in report:
            return Response(report, status=status.HTTP_404_NOT_FOUND)
        
        return Response(report, status=status.HTTP_200_OK)
# Create your views here.
