import asyncio
import unittest

from modules.memory.fix import Fix
from modules.memory.manager import MemoryManager
from modules.memory.snapshot import CellData, TableRow, TableSnapshot
from modules.memory.violation import Violation


class RecordingIOManager:
    def __init__(self):
        self.violations = None
        self.fixes = None

    def write_violations(self, violations):
        self.violations = violations

    def write_fixes(self, fixes):
        self.fixes = fixes


class MemoryManagerLockingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = object.__new__(MemoryManager)
        self.manager.__init__()
        self.run_id = "test-run"

    async def _populate_run(self):
        await self.manager.initialize_run(self.run_id, {"source": "test"})

        raw_snapshot = TableSnapshot(
            run_id=self.run_id,
            table="users",
            rows=[TableRow("1", {"name": CellData("Alice", [])})],
            created_at="2026-01-01T00:00:00",
        )
        raw_snapshot.processing_stage = "raw"
        await self.manager.store_snapshot(raw_snapshot)

        latest_snapshot = TableSnapshot(
            run_id=self.run_id,
            table="users",
            rows=[
                TableRow("1", {"name": CellData("Alice", [])}),
                TableRow("2", {"name": CellData("Bob", [])}),
            ],
            created_at="2026-01-01T00:00:01",
        )
        latest_snapshot.processing_stage = "fixed"
        await self.manager.store_snapshot(latest_snapshot)

        violation = Violation(
            id="v1",
            table="users",
            tuple_id="1",
            attr="name",
            constraint_type="value",
            description="invalid name",
            severity="warn",
            suggested_fix=None,
            detector_id="test",
            timestamp="2026-01-01T00:00:02",
        )
        fix = Fix(
            id="f1",
            table="users",
            tuple_id="1",
            attr="name",
            old="A",
            new="Alice",
            fix_type="value_correction",
            applied_by="test",
            timestamp="2026-01-01T00:00:03",
        )
        await self.manager.store_violations([violation], self.run_id, "users")
        await self.manager.store_fixes([fix], self.run_id, "users")
        return latest_snapshot, violation, fix

    async def test_persist_run_data_does_not_reenter_run_lock(self):
        latest_snapshot, violation, fix = await self._populate_run()
        io_manager = RecordingIOManager()

        await asyncio.wait_for(
            self.manager.persist_run_data(self.run_id, io_manager), timeout=0.2
        )

        self.assertEqual(io_manager.violations, [violation])
        self.assertEqual(io_manager.fixes, [fix])
        self.assertIs(
            await self.manager.get_snapshot(self.run_id, "users"), latest_snapshot
        )

    async def test_get_run_summary_does_not_reenter_run_lock(self):
        await self._populate_run()

        summary = await asyncio.wait_for(
            self.manager.get_run_summary(self.run_id), timeout=0.2
        )

        self.assertEqual(summary["metadata"], {"source": "test"})
        self.assertEqual(summary["total_snapshots"], 1)
        self.assertEqual(summary["total_violations"], 1)
        self.assertEqual(summary["total_fixes"], 1)
        self.assertEqual(
            summary["tables"],
            [{"table_name": "users", "rows": 2, "violations": 1, "fixes": 1}],
        )


if __name__ == "__main__":
    unittest.main()
