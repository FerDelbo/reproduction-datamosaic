import unittest
from unittest.mock import MagicMock

from modules.services.doc2db_service import Doc2DBService


class Doc2DBServiceProgressTests(unittest.TestCase):
    def test_structured_orchestrator_completion_marks_completed_and_saves_history(self):
        completion_steps = (
            ("step", "orchestrator_completion"),
            ("step", "orchestrator_completion_fallback"),
            ("step_name", "orchestrator_completion"),
            ("step_name", "orchestrator_completion_fallback"),
        )

        for field, value in completion_steps:
            with self.subTest(field=field, value=value):
                service = object.__new__(Doc2DBService)
                service.logger = MagicMock()
                service.task_queues = {}
                service.task_steps = {
                    "run-1": [
                        {
                            field: value,
                            "status": "completed",
                            "description": "structured completion event",
                        }
                    ]
                }
                context = object()
                service.running_tasks = {
                    "run-1": {
                        "status": "started",
                        "start_time": "2026-01-01T00:00:00",
                        "table_name": "users",
                        "error": None,
                        "running_context": context,
                    }
                }
                service._save_task_to_history = MagicMock()

                progress = service.get_task_progress("run-1")

                self.assertEqual(progress["status"], "completed")
                self.assertEqual(service.running_tasks["run-1"]["status"], "completed")
                self.assertIsNotNone(service.running_tasks["run-1"]["end_time"])
                service._save_task_to_history.assert_called_once_with(
                    "run-1", context, "completed"
                )


if __name__ == "__main__":
    unittest.main()
