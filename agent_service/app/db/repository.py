from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import PlanRecord, ExecutionRecord


class PlanRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_plan(
        self, user_input: str, plan_json: dict, status: str, conversation_id: str | None = None
    ) -> PlanRecord:
        record = PlanRecord(
            conversation_id=conversation_id,
            user_input=user_input,
            plan_json=plan_json,
            status=status,
        )
        self.session.add(record)
        await self.session.commit()
        return record

    async def get_history(self, conversation_id: str, limit: int = 20) -> list[PlanRecord]:
        result = await self.session.execute(
            select(PlanRecord)
            .where(PlanRecord.conversation_id == conversation_id)
            .order_by(PlanRecord.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class ExecutionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_step(
        self, step_id: str, tool: str, args_json: dict, conversation_id: str | None = None
    ) -> ExecutionRecord:
        record = ExecutionRecord(
            conversation_id=conversation_id,
            step_id=step_id,
            tool=tool,
            args_json=args_json,
            result="pending",
        )
        self.session.add(record)
        await self.session.commit()
        return record

    async def update_result(
        self, record_id: int, result: str, error_message: str | None = None
    ):
        result_query = await self.session.execute(
            select(ExecutionRecord).where(ExecutionRecord.id == record_id)
        )
        record = result_query.scalar_one_or_none()
        if record:
            record.result = result
            record.error_message = error_message
            await self.session.commit()
