class EmpleadoDTO:
    def __init__(self, id, usuario, nombre, apellido, rol, turno):
        self.id = id
        self.usuario = usuario
        self.nombre = nombre
        self.apellido = apellido
        self.rol = rol
        self.turno = turno

    def to_dict(self):
        return {
            "id": self.id,
            "usuario": self.usuario,
            "nombre": self.nombre,
            "apellido": self.apellido,
            "rol": self.rol,
            "turno": self.turno
        }


class RolDTO:
    def __init__(self, id_rol, descripcion):
        self.id_rol = id_rol
        self.descripcion = descripcion

    def to_dict(self):
        return {
            "id_rol": self.id_rol,
            "descripcion": self.descripcion
        }