import unittest

from app.routes.data import validate_import_content


def valid_payload():
    return {
        "version": "3.1.1",
        "projects": [{"id": 1, "name": "Проект", "archived": False}],
        "kits": [{"id": 2, "project_id": 1, "name": "Комплект"}],
        "employees": [{"id": 3, "full_name": "Иванов Иван", "kind": "own"}],
        "equipments": [{
            "id": 4, "name": "Прибор", "decimal_number": "АБВ.123",
            "serial_number": "SN-1", "status": "На складе",
            "project_id": 1, "kit_id": 2, "received_at": None
        }],
        "operations": [{
            "id": 5, "op_type": "issue", "employee_id": 3,
            "issuer_employee_id": 3, "recipient_name": "Петров Пётр",
            "created_at": None, "items": [4]
        }]
    }


class ImportValidationTests(unittest.TestCase):
    def test_accepts_export_shape(self):
        payload = valid_payload()
        self.assertIs(validate_import_content(payload), payload)

    def test_rejects_unknown_operation_type(self):
        payload = valid_payload()
        payload["operations"][0]["op_type"] = "delete"
        with self.assertRaisesRegex(ValueError, "тип операции"):
            validate_import_content(payload)

    def test_rejects_unknown_equipment_status(self):
        payload = valid_payload()
        payload["equipments"][0]["status"] = "Списано навсегда"
        with self.assertRaisesRegex(ValueError, "статус оборудования"):
            validate_import_content(payload)

    def test_rejects_missing_project_reference(self):
        payload = valid_payload()
        payload["equipments"][0]["project_id"] = 999
        with self.assertRaisesRegex(ValueError, "отсутствующий проект"):
            validate_import_content(payload)

    def test_rejects_duplicate_equipment_identifiers(self):
        payload = valid_payload()
        duplicate = dict(payload["equipments"][0])
        duplicate["id"] = 44
        duplicate["name"] = "Другой прибор"
        payload["equipments"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "повторяется serial_number"):
            validate_import_content(payload)

    def test_rejects_duplicate_items_in_operation(self):
        payload = valid_payload()
        payload["operations"][0]["items"] = [4, 4]
        with self.assertRaisesRegex(ValueError, "повторяется оборудование"):
            validate_import_content(payload)

    def test_rejects_non_object_root(self):
        with self.assertRaisesRegex(ValueError, "Корень JSON"):
            validate_import_content([])


if __name__ == "__main__":
    unittest.main()
