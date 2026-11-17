from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyBaseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
