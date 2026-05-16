"""VtfClient — sync client for the vtaskforge v2 API."""
from .transport import SyncTransport
from .managers import (
    AgentManager,
    BulkManager,
    ChannelMappingManager,
    LinkManager,
    LockManager,
    MemberManager,
    MilestoneManager,
    ProjectManager,
    ServiceAccountManager,
    TaskManager,
    UserManager,
    WorkplanManager,
)


class VtfClient:
    """Synchronous vtaskforge API client.

    Usage:
        vtf = VtfClient(url="http://localhost:8000", token="...")
        tasks = vtf.tasks.list(status="doing")
        task = vtf.tasks.get(task_id)
    """

    def __init__(
        self,
        url: str,
        token: str,
        timeout: float = 30.0,
        max_retries: int = 0,
        backoff_factor: float = 0.5,
    ):
        self._transport = SyncTransport(
            base_url=url,
            token=token,
            timeout=timeout,
            max_retries=max_retries,
            backoff_factor=backoff_factor,
        )
        self.tasks = TaskManager(self._transport)
        self.projects = ProjectManager(self._transport)
        self.workplans = WorkplanManager(self._transport)
        self.milestones = MilestoneManager(self._transport)
        self.agents = AgentManager(self._transport)
        self.links = LinkManager(self._transport)
        self.users = UserManager(self._transport)
        self.members = MemberManager(self._transport)
        self.locks = LockManager(self._transport)
        self.channel_mappings = ChannelMappingManager(self._transport)
        self.service_accounts = ServiceAccountManager(self._transport)
        self.bulk = BulkManager(self._transport)

    def health(self) -> dict:
        """Check API health."""
        return self._transport.get("/v2/health")

    def close(self):
        self._transport.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
