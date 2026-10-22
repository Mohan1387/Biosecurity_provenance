"""Read-only verification of database-backed provenance for the configured DB."""
import asyncio

from sqlalchemy import select

from app.database import async_session
from app.models import DataAccessLog, OrcidProfile, OrcidPublication, QueryHistory, UserWarning
from app.services.provenance import verify_row


async def main() -> None:
    counts = {}
    async with async_session() as db:
        for model, component in (
            (QueryHistory, "logger"),
            (DataAccessLog, "logger"),
            (OrcidPublication, "profiler"),
            (OrcidProfile, "profiler"),
            (UserWarning, "detector"),
        ):
            rows = (await db.execute(select(model))).scalars().all()
            for row in rows:
                await verify_row(db, row, component)
            counts[model.__tablename__] = len(rows)
    print("Verified signed rows:", counts)


if __name__ == "__main__":
    asyncio.run(main())
