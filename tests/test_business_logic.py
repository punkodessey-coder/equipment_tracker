import os
import tempfile
import unittest
from datetime import datetime, timedelta

from app import create_app, db
from app.models import User, Project, Equipment, Employee, Operation, OperationItem


class BusinessLogicTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "UPLOAD_FOLDER": self.temp_dir.name,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.user = User(username="test-user", role="admin", must_change_password=False)
        self.user.set_password("test-password", keep_plain=False)
        db.session.add(self.user)
        db.session.flush()
        self.project = Project(user_id=self.user.id, name="Тестовый проект", archived=False)
        self.employee = Employee(user_id=self.user.id, full_name="Иванов Иван", kind="own")
        db.session.add_all([self.project, self.employee])
        db.session.flush()
        self.equipment = Equipment(
            user_id=self.user.id, name="Тестовый прибор", project_id=self.project.id,
            status="На складе", serial_number="TEST-001"
        )
        db.session.add(self.equipment)
        db.session.commit()

        self.client = self.app.test_client()
        response = self.client.post("/auth/login", data={
            "username": "test-user", "password": "test-password"
        }, follow_redirects=False)
        self.assertIn(response.status_code, (302, 303))

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.temp_dir.cleanup()

    def add_operation(self, op_type, recipient, created_at, equipment=None):
        equipment = equipment or self.equipment
        op = Operation(
            user_id=self.user.id, op_type=op_type, recipient_name=recipient,
            issuer_employee_id=self.employee.id, created_at=created_at,
            seq_number=(db.session.query(db.func.max(Operation.seq_number))
                        .filter_by(user_id=self.user.id).scalar() or 0) + 1,
        )
        db.session.add(op)
        db.session.flush()
        db.session.add(OperationItem(operation_id=op.id, equipment_id=equipment.id))
        equipment.status = f"Выдано ({recipient})" if op_type == "issue" else "На складе"
        db.session.commit()
        return op

    def test_cannot_delete_equipment_with_movement_history(self):
        self.add_operation("issue", "Петров Пётр", datetime(2026, 1, 1))
        response = self.client.post(f"/equipment/{self.equipment.id}/delete")
        self.assertIn(response.status_code, (302, 303))
        self.assertIsNotNone(db.session.get(Equipment, self.equipment.id))
        self.assertEqual(OperationItem.query.filter_by(equipment_id=self.equipment.id).count(), 1)
        self.assertEqual(Operation.query.count(), 1)

    def test_can_delete_equipment_without_movement_history(self):
        equipment_id = self.equipment.id
        response = self.client.post(f"/equipment/{equipment_id}/delete")
        self.assertIn(response.status_code, (302, 303))
        self.assertIsNone(db.session.get(Equipment, equipment_id))

    def test_cannot_archive_project_with_issued_equipment(self):
        self.equipment.status = "Выдано (Петров Пётр)"
        db.session.commit()
        response = self.client.post(f"/projects/{self.project.id}/archive")
        self.assertIn(response.status_code, (302, 303))
        db.session.refresh(self.project)
        db.session.refresh(self.equipment)
        self.assertFalse(self.project.archived)
        self.assertEqual(self.equipment.status, "Выдано (Петров Пётр)")

    def test_can_archive_project_when_no_equipment_is_issued(self):
        response = self.client.post(f"/projects/{self.project.id}/archive")
        self.assertIn(response.status_code, (302, 303))
        db.session.refresh(self.project)
        db.session.refresh(self.equipment)
        self.assertTrue(self.project.archived)
        self.assertEqual(self.equipment.status, "Архивное")
        self.assertEqual(self.equipment.status_before_archive, "На складе")

    def test_cannot_delete_operation_if_later_operation_exists(self):
        first_time = datetime(2026, 1, 1)
        first = self.add_operation("issue", "Петров Пётр", first_time)
        second = self.add_operation("receive", "Петров Пётр", first_time + timedelta(days=1))
        response = self.client.post(f"/operations/delete/{first.id}")
        self.assertIn(response.status_code, (302, 303))
        self.assertIsNotNone(db.session.get(Operation, first.id))
        self.assertIsNotNone(db.session.get(Operation, second.id))
        self.assertEqual(self.equipment.status, "На складе")

    def test_cannot_edit_operation_if_later_operation_exists(self):
        first_time = datetime(2026, 1, 1)
        first = self.add_operation("issue", "Петров Пётр", first_time)
        self.add_operation("receive", "Петров Пётр", first_time + timedelta(days=1))
        response = self.client.post(f"/operations/edit/{first.id}", data={
            "op_type": "issue",
            "employee_name": "Сидоров Сергей",
            "issuer_name": self.employee.full_name,
            "equipment_ids": str(self.equipment.id),
            "comment": "Изменение задним числом",
        })
        self.assertIn(response.status_code, (302, 303))
        db.session.refresh(first)
        self.assertEqual(first.recipient_name, "Петров Пётр")
        self.assertEqual(first.op_type, "issue")
        self.assertEqual(Operation.query.count(), 2)

    def test_upgrade_schema_cli_command_runs(self):
        result = self.app.test_cli_runner().invoke(args=["upgrade-schema"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Схема базы данных обновлена.", result.output)
        self.assertTrue(db.inspect(db.engine).has_table("equipments"))
        self.assertTrue(db.inspect(db.engine).has_table("operation_items"))

    def test_deleting_latest_issue_recalculates_equipment_status(self):
        issue = self.add_operation("issue", "Петров Пётр", datetime(2026, 1, 1))
        self.assertEqual(self.equipment.status, "Выдано (Петров Пётр)")
        response = self.client.post(f"/operations/delete/{issue.id}")
        self.assertIn(response.status_code, (302, 303))
        db.session.refresh(self.equipment)
        self.assertIsNone(db.session.get(Operation, issue.id))
        self.assertEqual(self.equipment.status, "На складе")


if __name__ == "__main__":
    unittest.main()
