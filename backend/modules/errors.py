"""errors.py - error ที่ระบบรู้จัก

Module ต่าง ๆ จะ raise AppError เมื่อมีปัญหาที่ผู้ใช้ควรรู้ (เช่น ไม่พบข้อมูล, ไม่มีสิทธิ์)
ส่วน router/server จะจับ AppError แล้วแปลงเป็น JSON อ่านง่าย - ผู้ใช้ไม่เห็น traceback
"""


class AppError(Exception):
    """error ทั่วไปของระบบ

    code    = รหัสสำหรับโปรแกรม (เช่น "NOT_FOUND")
    message = ข้อความภาษาไทยที่แสดงให้ผู้ใช้อ่าน
    status  = HTTP status code
    fields  = dict ของ error รายช่องข้อมูล เช่น {"price": "ราคาต้องไม่ต่ำกว่า 0"}
    details = dict ข้อมูลเพิ่มสำหรับโปรแกรม (ไม่แสดงเป็นข้อความให้ผู้ใช้)
    """

    def __init__(self, code, message, status=400, fields=None, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.fields = fields or {}
        self.details = details or {}      # ข้อมูลเพิ่มสำหรับโปรแกรม เช่น {"available_at": "..."} (ไม่ใช่ข้อความรายช่อง)

    def to_dict(self):
        """แปลงเป็น dict สำหรับส่งกลับเป็น JSON"""
        error = {"code": self.code, "message": self.message, "fields": self.fields}
        if self.details:
            error["details"] = self.details
        return {"error": error}


class StorageError(AppError):
    """error จากการอ่าน/เขียนไฟล์ข้อมูล
    detail เก็บรายละเอียดสำหรับ developer (เขียนลง log เท่านั้น ไม่ส่งให้ผู้ใช้)
    """

    def __init__(self, code, message, detail="", status=500):
        super().__init__(code, message, status=status)
        self.detail = detail


# ---- ฟังก์ชันช่วยสร้าง error ที่ใช้บ่อย (อ่านง่ายตอน raise) ----
def not_found(what):
    return AppError("NOT_FOUND", "ไม่พบ " + what, 404)


def unauthorized_error(message="กรุณาเข้าสู่ระบบ"):
    return AppError("UNAUTHORIZED", message, 401)


def forbidden_error(message="ไม่มีสิทธิ์ดำเนินการ"):
    return AppError("FORBIDDEN", message, 403)


def validation_error(fields, message="ข้อมูลไม่ถูกต้อง"):
    return AppError("VALIDATION_ERROR", message, 400, fields)


def conflict_error(code, message):
    return AppError(code, message, 409)
