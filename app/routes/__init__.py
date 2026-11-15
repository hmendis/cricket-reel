"""One APIRouter per screen (R30). app.main includes them all, in this order."""
from . import arrange, describe, export, feedback, jobs, matches, review, settings, sheet, sync

ROUTERS = [m.router for m in (settings, matches, sheet, sync, jobs, review, arrange, feedback, export, describe)]
