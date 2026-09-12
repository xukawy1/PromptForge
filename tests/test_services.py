from pathlib import Path
from app.database.migrations import migrate
from app.database.seed import seed_defaults
from app.database.repositories.core import PromptRepository, SourceRepository, TaskRepository
from app.services.dashboard_service import DashboardService
from app.services.task_service import TaskService

def test_dashboard_counts(tmp_path: Path):
    db=tmp_path/'x.db'; migrate(db); seed_defaults(db)
    SourceRepository(db).create({'title':'测试资料','source_type':'manual'})
    PromptRepository(db).create({'title':'测试Prompt','prompt_text':'cinematic portrait'})
    stats=DashboardService(db).stats()
    assert stats['sources']==1 and stats['prompts']==1

def test_task_service_persistence(tmp_path: Path):
    db=tmp_path/'x.db'; migrate(db); seed_defaults(db)
    s=TaskService(db); s.create('t1','test',{'a':1}); s.update('t1','running',30,started=True); s.update('t1','completed',100,{'ok':True},finished=True)
    row=TaskRepository(db).get('t1')
    assert row['status']=='completed' and row['progress']==100
